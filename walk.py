import os

for a,b,c in os.walk("/home/cc1/Git/"):

    if '.git' in b:
        print('----------------')
        print(f'{a} contain a git folder')

