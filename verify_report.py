"""
A script to parse and verify Arlo audit reports. Because the reports are
custom formats, we can't rely on other parsers.
"""

import sys
import csv
import itertools
import random
from decimal import Decimal

def parse(filename):
    """
    Parses the csv file and returns relevant data
    """

    info = {
        'ELECTION INFO': [],
        'CONTESTS': [],
        'AUDIT SETTINGS': [],
        'AUDIT BOARDS': [],
        'ROUNDS': [],
        'SAMPLED BALLOTS': [],
    }

    cur_label = 'ELECTION INFO'

    header_row = False
    keys = []
    for line in open(filename):
        data = line.strip().strip('#').strip()

        # This is a label row, so parse the label
        if data in info:
            cur_label = data
            header_row = True
            keys = []
            continue

        # This is a header row, so parse the header
        if header_row:
            keys = data.split(',')
            header_row = False
            continue


        # This is a non-empty, non-label, non-header row, so parse data
        if data:
            raw = list(csv.reader([data]))[0]
            info[cur_label].append(dict(zip(keys, raw)))

    return info

def compute_diluted_margin(contest):
    """
    Compute the diluted margin for the given contest
    """
    candidates = []

    for cand in contest['Tabulated Votes'].split(';'):
        name = cand.split(':')[0].strip()
        votes = int(cand.split(':')[1].strip())

        candidates.append((name, votes))

    # Find winners
    num_winners = int(contest['Number of Winners'])

    winners = sorted(candidates, key=lambda x: x[1], reverse=True)[:num_winners]
    losers = sorted(candidates, key=lambda x: x[1], reverse=True)[num_winners:]

    worst_winner = winners[-1]
    best_loser = losers[0]


    total = int(contest['Total Ballots Cast'])
    margin = (worst_winner[1] - best_loser[1])/total

    return worst_winner[0], best_loser[0], winners, losers, margin

def process_ballot_polling_ballots(ballots, contests, risk_limit ):
    """
    Processes the ballots for the contests, computing p-values
    """

    # First map all ballots to ticket numbers
    mapped_ballots = {}
    for ballot in ballots:
        for contest in contests:
            ticket_numbers = ballot['Ticket Numbers: ' + contest['Contest Name']].split(':')[-1].strip().split(',')

            for number in ticket_numbers:
                if float(number) in mapped_ballots:
                    number = float(number) + 10**-10
                mapped_ballots[float(number)] = ballot


    # Set up test statistics
    T = {}
    S_wl = {}
    total_T = {}
    finished = {}

    winners = {}
    losers = {}

    winner_names = {}
    loser_names = {}


    sample_results = {}
    for c in contests:
        contest = c['Contest Name']
        ww, bl, winners[contest], losers[contest], margin = compute_diluted_margin(c)


        sample_results[contest] = {}

        winner_names[contest] = [w[0] for w in winners[contest]]
        loser_names[contest] = [w[0] for w in losers[contest]]

        T[contest] = {}
        total_T[contest] = {}
        S_wl[contest] = {}

        for winner in winners[contest]:
            S_wl[contest][winner[0]] = {}
            T[contest][winner[0]] = {}
            total_T[contest][winner[0]] = {}
            for loser in losers[contest]:
                T[contest][winner[0]][loser[0]] = 1
                total_T[contest][winner[0]][loser[0]] = 1
                S_wl[contest][winner[0]][loser[0]] = (winner[1])/(loser[1] +
                        winner[1])

    is_finished = {}
    for c in contests:
        contest = c['Contest Name']
        is_finished[contest] = False

    ctr = 0


    phantoms = 0
    for ballot in sorted(mapped_ballots):
        phantom = {}
        if mapped_ballots[ballot]['Audited?'] != 'AUDITED':
            phantoms += 1
            for c in contests:
                contest = c['Contest Name']
                phantom[contest]= losers[contest][0][0]

                # this code lets us hypothesize about what the phantoms might be.
                # Not recommended.
                #flip = random.random()
                #if flip  < .506:
                #    phantom[contest] = winners[contest][0][0]
                #elif .506 < flip < .985:
                #    phantom[contest] = losers[contest][0][0]
                #else:
                #    phantom[contest] = losers[contest][1][0]


        ctr += 1
        for c in contests:
            contest = c['Contest Name']

            if phantom:
                result = phantom[contest]
            else:
                result = mapped_ballots[ballot][f'Audit Result: {contest}']


            if result in sample_results[contest]:
                sample_results[contest][result] += 1
            else:
                sample_results[contest][result] = 1

            if contest not in finished:
                finished[contest] = set()


            if result in [w[0] for w in winners[contest]]:
                for los in losers[contest]:
                    l = los[0]
                    total_T[contest][result][l] *= S_wl[contest][result][l]/0.5
                    if (result, l) in finished[contest]:
                        continue
                    T[contest][result][l] *= S_wl[contest][result][l]/0.5
            elif result in [l[0] for l in losers[contest]]:
                for win in winners[contest]:
                    w = win[0]
                    total_T[contest][w][result] *= (1 -
                            S_wl[contest][w][result])/0.5
                    if (w, result) in finished[contest]:
                        continue
                    T[contest][w][result] *= (1 - S_wl[contest][w][result])/0.5

            for w in T[contest]:
                for l in T[contest][w]:
                    if T[contest][w][l] >= 1/risk_limit:
                        finished[contest].add((w, l))

            complete_set = itertools.product(\
                                    winner_names[contest],
                                    loser_names[contest])
            if not is_finished[contest] and finished[contest] == set(complete_set):
                print(f'Could have stopped at {ctr} in {contest}')
                is_finished[contest] = True


    print('{} phantoms were found and turned into zombies.'.format(phantoms))
    print()
    for contest in sample_results:
        print('\tSample results for {}'.format(contest))
        contained = 0
        for cand in sample_results[contest]:
            if not cand:
                continue
            print('\t\t{}: {}'.format(cand, sample_results[contest][cand]))
            contained += sample_results[contest][cand]

        print(f'\t{contained} ballots contained this contest')
        print()

    results = {}
    seq_p = {}
    tot_p = {}
    for contest in T:
        seq_p[contest]= 0
        tot_p[contest] = 0
        for w in T[contest]:
            for l in T[contest][w]:
                seq_p[contest] = max(seq_p[contest], 1/T[contest][w][l])
                tot_p[contest] = max(tot_p[contest], 1/total_T[contest][w][l])

    return tot_p, seq_p

def process_ballot_comparison_ballots(ballots, contests, risk_limit ):


    tot_p = {}
    seq_p = {}
    p = Decimal(1.0)
    gamma: Decimal = Decimal(1.03905)  # This gamma is used in Stark's tool, AGI, and CORLA

    # This sets the expected number of one-vote misstatements at 1 in 1000
    o1: Decimal = Decimal(0.001)
    u1: Decimal = Decimal(0.001)

    # This sets the expected two-vote misstatements at 1 in 10000
    o2: Decimal = Decimal(0.0001)
    u2: Decimal = Decimal(0.0001)

    for contest in contests:

        results = {}
        print(contest)
        for cand in contest['Tabulated Votes'].split(';'):
            name = cand.split(':')[0].strip()
            votes = int(cand.split(':')[1].strip())
            results[name] = votes

        #contest = c['Contest Name']
        cn = contest['Contest Name']
        N = int(contest['Total Ballots Cast'])
        ww, bl, _, _, diluted_margin = compute_diluted_margin(contest)
        V = Decimal(diluted_margin * N)

        if diluted_margin == 0:
            U = Decimal("inf")
        else:
            U = 2 * gamma / Decimal(diluted_margin)


        for ballot in ballots:
            if ballot ['Audited?'] != 'AUDITED':
                continue
            reported = ballot['CVR Result: ' + cn]
            audited = ballot['Audit Result: ' + cn]

            V_wl = results[ww] - results[bl]


            if reported != audited:
                if reported == ww and audited == bl:
                    e = 2.0
                elif reported != ww and reported != bl and audited == bl:
                    e = 1.0
                else:
                    e = 0

                e_r = e / V_wl
            else:
                e_r = 0

            U = 2 * gamma / Decimal(diluted_margin)
            denom = (2 * gamma) / V
            p_b = (1 - 1 / U) / (1 - (Decimal(e_r) / denom))

            # TODO fix
            multiplicity = 1 # ballot['Ticket Numbers: ' + contest]
            p *= p_b ** multiplicity

        tot_p[cn] = p
        seq_p[cn]  = p
    return tot_p, seq_p

def main():
    """
    The main function
    """

    if len(sys.argv) < 2:
        print('Usage: verify_report.py [report.csv]...')
        sys.exit(0)


    print('Verifier for VotingWorks\' Arlo Audit Reports\n')
    filenames = sys.argv[1:]

    for file in filenames:
        parsed = parse(file)

        name = ''
        state = ''

        name = parsed['ELECTION INFO'][0]['Election Name']
        state = parsed['ELECTION INFO'][0]['State']
        print('Verifying report {}, for election {} in {}\n'.format(
            file, name, state))

        print('\tFound {} contests:'.format(len(parsed['CONTESTS'])))
        for contest in parsed['CONTESTS']:

            worst_winner, best_loser, winners, losers, margin = compute_diluted_margin(contest)

            print('\t\t{} ({}):'.format(
                contest['Contest Name'],
                ['opportunistic', 'targeted'][contest['Targeted?'] == 'Targeted']
                ))

            for winner in winners:
                if winner[0] == worst_winner:
                    print('\t\t\t{:20s}: {} votes (worst winner)'.format(winner[0], winner[1]))
                else:
                    print('\t\t\t{:20s}: {} votes'.format(winner[0], winner[1]))
            for loser in losers:
                if loser[0] == best_loser:
                    print('\t\t\t{:20s}: {} votes (best loser)'.format(loser[0], loser[1]))
                else:
                    print('\t\t\t{:20s}: {} votes'.format(loser[0], loser[1]))

            print('\t\t\tWorst Winner: {:20s}\n\
                         Best Loser: {:20s}\n\
                         Diluted margin: {:2.1f}%'.format(
                             worst_winner,
                             best_loser,
                             margin*100))

            print()

        print('\tFound {} sampled ballots'.format(
            len(parsed['SAMPLED BALLOTS'])))

        print()

        risk_limit = float(parsed['AUDIT SETTINGS'][0]['Risk Limit'].strip('%'))/100

        audit_type = parsed['AUDIT SETTINGS'][0]['Audit Type']

        if audit_type == 'BALLOT_POLLING':
            tot_p, seq_p = process_ballot_polling_ballots(
                parsed['SAMPLED BALLOTS'],
                parsed['CONTESTS'],
                risk_limit,
                )
        elif audit_type == 'BALLOT_COMPARISON':
            tot_p, seq_p = process_ballot_comparison_ballots(
                parsed['SAMPLED BALLOTS'],
                parsed['CONTESTS'],
                risk_limit,
                )
        else:
            print('Audit type {} not supported'.format(audit_type))
            return



        print()

        for rnd in parsed['ROUNDS']:
            r_num = rnd['Round Number']
            try:
                pval = float(rnd['P-Value'])
            except:
                pval =  None
            contest = rnd['Contest Name']

            if not pval:
                print('Audit did not include a p-value in Round {} for race {}'.format(
                r_num, contest))
            else:
                print('Audit reported p of {:1.4f} in Round {} for race {}'.format(
                pval,
                r_num, contest))

            print('\tAttained total p of {:1.9f}, sequential p of {:1.4f}'.format(
                tot_p[contest],
                seq_p[contest]))

            print()

        print()

if __name__ == '__main__':
    main()
