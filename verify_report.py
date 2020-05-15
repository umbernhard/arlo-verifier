"""
A script to parse and verify Arlo audit reports. Because the reports are
custom formats, we can't rely on other parsers.
"""

import sys

def parse(filename):
    """
    Parses the csv file and returns relevant data
    """

    info = {
        'ELECTION INFO': {},
        'CONTESTS': [],
        'AUDIT SETTINGS': {},
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

            if cur_label not in ['ELECTION INFO', 'AUDIT SETTINGS']:
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
            raw = data.split(',')

            if cur_label not in ['ELECTION INFO', 'AUDIT SETTINGS']:
                info[cur_label].append(dict(zip(keys, raw)))
            else:
                # These two sections pack their keys with their data, not ahead of
                # it
                info[cur_label][raw[0]] = raw[1]


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

    worst_winner = sorted(candidates, key=lambda x: x[1], reverse=True)[num_winners - 1]
    best_loser = sorted(candidates, key=lambda x: x[1], reverse=True)[num_winners]

    total = int(contest['Total Ballots Cast'])
    margin = (worst_winner[1] - best_loser[1])/total

    return worst_winner[0], best_loser[0], margin

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

        print('Verifying report {}, for election {} in {}\n'.format(
            file, \
            parsed['ELECTION INFO']['Election Name'], \
            parsed['ELECTION INFO']['State']))

        print('\tFound {} contests:'.format(len(parsed['CONTESTS'])))
        for contest in parsed['CONTESTS']:

            worst_winner, best_loser, margin = compute_diluted_margin(contest)

            print('\t\t{}:'.format(
                contest['Contest Name'],
                ))

            print('\t\t\tWorst Winner: {:20s}\n\
                         Best Loser: {:20s}\n\
                         Diluted margin: {:2.1f}%\n\
                         Targeted? {}'.format(
                             worst_winner,
                             best_loser,
                             margin*100,
                             contest['Targeted?'] == 'Targeted'))


    print()

if __name__ == '__main__':
    main()
