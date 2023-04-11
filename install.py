#! /usr/bin/python3

import os
import sys
import subprocess
from shutil import copyfile, copytree

def install_linux():

    home = os.path.expanduser('~')
    path = os.path.join(home, '.GitHUD')
    current_dir = os.getcwd()

    _, user = os.path.split(home)

    if not os.path.exists(path):
        os.mkdir(path)

    copyfile(f'{current_dir}/main.py', f'{path}/main.py')
    copyfile(f'{current_dir}/window.ui', f'{path}/window.ui')
    copyfile(f'{current_dir}/githud_icon.png', f'{path}/githud_icon.png')
    copytree(f'{current_dir}/icon/', f'{path}/icon/', dirs_exist_ok=True)

    if not os.path.exists(f'{path}/user.conf'):
        file = open(f'{path}/user.conf', 'w')
        file.write('---\n')
        file.write(f'path: [{home}/Git]\n')
        file.write(f'user: {user}\n')
        file.close()

    file = open(f'{path}/GitHUD.desktop', 'w')
    file.write('#!/usr/bin/env xdg-open\n')
    file.write('[Desktop Entry]\n')
    file.write('Name=GitHUD\n')
    file.write('GenericName=GitHUD\n')
    file.write(f'Exec=python3 {path}/main.py\n')
    file.write('Terminal=False\n')
    file.write('Type=Application\n')
    file.write(f'Icon={path}/githud_icon.png\n')
    file.close()

    # print("Linux install not yet implemented!")
    # pass

def install_windows():
    print("Windows install not yet implemented!")
    pass

cmd = 'pip install -r requirements.txt'
ret = subprocess.run(cmd, shell=True, text=True)

if sys.platform == 'linux':
    install_linux()

elif sys.platform == 'windows':
    install_windows()

else:
    print(f'OS {sys.platform} not yet supported!')


