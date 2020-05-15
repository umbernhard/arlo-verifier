"""
A script to parse and verify Arlo audit reports. Because the reports are
custom formats, we can't rely on other parsers.
"""

import sys
import csv
import itertools

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

def process_ballots(ballots, contests, risk_limit, rnd_num):
    """
    Processes the ballots for the contests, computing p-values
    """

    # First map all ballots to ticket numbers
    mapped_ballots = {}
    for ballot in ballots:
        ticket_numbers = ballot['Ticket Numbers'].split(':')[-1].strip().split(',')
        for number in ticket_numbers:
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
    for c in contests:
        contest = c['Contest Name']
        ww, bl, winners[contest], losers[contest], margin = compute_diluted_margin(c)

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

    is_finished = False
    ctr = 0
    for ballot in sorted(mapped_ballots):
        if mapped_ballots[ballot]['Audited?'] != 'AUDITED':
            continue

        ctr += 1
        for c in contests:
            contest = c['Contest Name']
            result = mapped_ballots[ballot][f'Audit Result: {contest}']
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
            if not is_finished and finished[contest] == set(complete_set):
                print(f'Could have stopped at {ctr}')
                is_finished = True



    results = {}
    seq_p = {}
    tot_p = {}
    for contest in T:
        seq_p[contest]= 100
        tot_p[contest] = 100
        for w in T[contest]:
            for l in T[contest][w]:
                seq_p[contest] = min(seq_p[contest], T[contest][w][l])
                tot_p[contest] = min(tot_p[contest], total_T[contest][w][l])

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

        for rnd in parsed['ROUNDS']:
            r_num = rnd['Round Number']

            tot_p, seq_p = process_ballots(
                parsed['SAMPLED BALLOTS'],
                parsed['CONTESTS'],
                risk_limit,
                r_num)

            pval = rnd['P-Value']
            if not pval:
                pval = 'N/A'
            contest = rnd['Contest Name']

            print('Audit reported p of {} in Round {} for race {}'.format(
                pval,
                r_num, contest))

            print('\tAttained total p of {:1.4f}, sequential p of {:1.4f}'.format(
                1/tot_p[contest],
                1/seq_p[contest]))

            print()


        print()

if __name__ == '__main__':
    main()
