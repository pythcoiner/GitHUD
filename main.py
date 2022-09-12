

import os
import sys
import subprocess
import logging
import time

from yaml import load, Loader

from pathlib import Path

from PySide2.QtWidgets import QApplication, QWidget, QLabel, QTableWidgetItem, QPushButton, QStyle, QMainWindow, QTreeWidget, QTreeWidgetItem
from PySide2.QtCore import QFile, QThread, Signal, Qt
from PySide2 import QtCore
from PySide2.QtGui import QIcon, QPixmap, QPalette, QColor, QClipboard, QGuiApplication
from PySide2.QtUiTools import QUiLoader


FORMAT = '%(message)s'
logging.basicConfig(format=FORMAT)
log = logging.getLogger()
log.setLevel(35)

class GitHUD(QWidget):

    def __init__(self):
        QWidget.__init__(self)
        # get config data
        path = os.fspath(Path(__file__).resolve().parent / "user.conf")
        self.config_file = open(path, 'r')
        self.config = load(self.config_file, Loader)
        self.directory_paths = self.config['path']

        self.ui = None
        self.build_gui()
        self.tree = self.ui.tree
        self.tree_list = []

        self.projects = []
        self.sections = []
        self.branches = []
        self.local_branches = []
        self.remotes = {}
        self.selected_branch = None

        self.project = None
        self.section = None
        self.branch = None
        self.path = None

        self.branch_chg_lock = False
        self.update_brch_lock = False
        self.pull_lock = False

        self.change_list = []
        self.cached_change_list = []

        self.ui.combo_project.currentTextChanged.connect(self.update_section)
        self.ui.combo_section.currentTextChanged.connect(self.update_branch)
        self.ui.combo_branch.currentTextChanged.connect(self.on_branch_choice)

        self.ui.b_pull.clicked.connect(self.on_pull)
        self.ui.b_push.clicked.connect(self.on_push)
        self.ui.b_commit.clicked.connect(self.on_commit)
        self.ui.b_commit_push.clicked.connect(self.on_commit_push)
        self.ui.b_ignore.clicked.connect(self.on_ignore)
        self.ui.b_merge.clicked.connect(self.on_merge)
        self.list_projects()

        self.update_project()

    def build_gui(self):
        loader = QUiLoader()
        path = os.fspath(Path(__file__).resolve().parent / "window.ui")
        ui_file = QFile(path)
        # ui_file = QFile('window.ui')
        ui_file.open(QFile.ReadOnly)
        self.ui = loader.load(ui_file, self)

        ui_file.close()

    def list_projects(self):

        repo_list = []
        for i in self.directory_paths:
            if not os.path.exists(i):
                raise ValueError("Path dont exist, please check user.conf")

            for a,b,c in os.walk(i):
                if '.git' in b:
                    d = a
                    a = a.split("/")

                    prj = ("/".join(a[:-1])).split(i)
                    if len(prj) == 1:
                        prj = prj[0]
                    else:
                        prj = prj[-1]

                    repo_list.append([prj,[a[-1:][0],d]])

        project_list = []
        while len(repo_list) > 0:
            project = repo_list.pop()
            project[1] = [project[1]]

            buff = []
            for i in repo_list:
                if i[0] == project[0]:
                    project[1].append(i[1])
                else:
                    buff.append(i)

            project_list.append(project)
            repo_list = buff
        projects = {}
        for i in project_list:
            projects[i[0]] = i[1]

        self.projects = projects

    def update_project(self):
        self.ui.combo_project.clear()
        self.ui.combo_project.addItems(self.projects)

    def update_section(self):
        self.ui.combo_section.clear()
        self.project = self.ui.combo_project.currentText()
        txt = f"Project: {self.project}"
        self.set_label(txt)
        self.sections = self.projects[self.project]
        for i in self.sections:
            self.ui.combo_section.addItem(i[0])

        txt = f'{self.section[0]} : {self.selected_branch}'
        self.set_label(txt)

    def update_branch(self, label = True):

        if not self.update_brch_lock :
            self.update_brch_lock = True
            section = self.ui.combo_section.currentText()
            for i in self.sections:
                if i[0] == section:
                    self.section = i
                    break

            self.path = self.section[1]
            self.get_branches()
            self.get_remotes()
            self.get_selected_branch()
            self.process_branches()
            self.check_changes()
            self.ui.combo_branch.clear()
            self.ui.combo_branch.addItems(self.branches + ['--new--'])
            branches = self.branches
            branches.remove(self.selected_branch)
            self.ui.combo_merge.clear()
            self.ui.combo_merge.addItems(branches)

            txt = f'{self.section[0]} : {self.selected_branch}'
            if label:
                self.set_label(txt)

            self.update_brch_lock = False

    def on_branch_choice(self):
        branch = self.ui.combo_branch.currentText()
        if not branch == '--new--':
            self.on_branch_change(branch)
        else:
            self.on_new_branch()

    def on_branch_change(self,branch):
        if self.branch_chg_lock :
            return
        self.branch_chg_lock = True
        if branch is None or len(branch) == 0:
            self.branch_chg_lock = False
            return
        self.get_selected_branch()
        self.get_branches()

        if branch in self.local_branches:
            self.do_checkout(branch)
        else:
            self.do_make_branch(branch)
            self.do_checkout(branch)
            self.do_pull()
        self.branch_chg_lock = False

    def on_pull(self):
        self.do_pull()

    def on_push(self):
        self.do_push()

    def on_commit(self):

        if len(self.cached_change_list) > 0 or len(self.change_list) > 0:

            if self.ui.msg.text() == '':
                txt = f'commit message is needed!'
                self.set_label(txt)
                return False

            for i in self.tree_list:

                if (i.checkState(0) == Qt.CheckState.Checked):
                    if ' ' in i.text(0):
                        filename = f"'{i.text(0)}'"
                    else:
                        filename = i.text(0)
                    if not self.do_add(filename):
                        return False

            if not self.do_commit():
                self.check_changes()
                return False

            self.check_changes()
            return True

        else:
            txt = f'nothing to commit!'
            self.set_label(txt)
            return False

    def on_commit_push(self):

        if not self.on_commit():
            return False

        self.do_push()

    def on_merge(self):
        _from = self.ui.combo_merge.currentText()
        if _from != '':
            self.do_merge(_from)
        else:
            txt = f'no branch to merge from!'
            self.set_label(txt)

    def on_ignore(self):

        for i in self.tree_list:

            if (i.checkState(0) == Qt.CheckState.Checked):
                if ' ' in i.text(0):
                    filename = f"'{i.text(0)}'"
                else:
                    filename = i.text(0)

                self.do_ignore(filename)

        self.check_changes()

    def on_new_branch(self):
        name = self.ui.msg.text()
        if name == '':
            txt = f"need define a branch name!"
            self.set_label(txt)
        elif name not in self.branches :
            self.do_make_branch(name)
            self.ui.msg.clear()
        else:
            txt = f"branch already exist"
            self.set_label(txt)

    def do_checkout(self, branch):
        self.get_selected_branch()
        if branch is not None and branch != '' and branch != self.selected_branch:
            checkout = f'cd {self.path} && git commit -m "change_branch" ; git checkout {branch}'
            ret = subprocess.run(checkout, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if ret.returncode != 0:
                tooltip = checkout + '\n     ==>    \n' + ret.stderr
                self.set_label('Cannot change branch',tooltip)
            else:
                txt = f'{self.section[0]} : {branch}'
                tooltip = checkout + '\n     ==>    \n' + ret.stdout
                self.set_label(txt, tooltip)
            self.update_branch(label=False)

    def do_merge(self, _from):
        cmd = f'cd {self.path} && git merge {_from}'
        ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if ret.returncode != 0:
            tooltip = cmd + '\n     ==>    \n' + ret.stderr
            txt = f'merge fail!'
            self.set_label(txt, tooltip)
            return False
        else:
            txt = f'merged successfully'
            tooltip = cmd + '\n     ==>    \n' + ret.stdout
            self.set_label(txt, tooltip)
            return True

    def do_ignore(self,file):
        path = self.path + '/' + file
        gitignore_path = self.path + '/.gitignore'
        if not os.path.exists(path):
            txt = f"file don't exist!"
            self.set_label(txt)
            return False

        f = open(gitignore_path, 'a')
        f.write(file +'\n')
        f.close()
        return True

    def do_add(self,file):
        cmd = f'cd {self.path} && git add {file}'
        ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if ret.returncode != 0:
            tooltip = cmd + '\n     ==>    \n' + ret.stderr
            txt = f'add fail!'
            self.set_label(txt, tooltip)
            return False
        else:
            txt = f'file add successfully'
            tooltip = cmd + '\n     ==>    \n' + ret.stdout
            self.set_label(txt, tooltip)
            return True

    def do_commit(self):
        msg = self.ui.msg.text()
        if msg == '':
            txt = f'a message i needed for commit!'
            self.set_label(txt)
            return False

        cmd = f"cd {self.path} && git commit -m '{msg}'"
        ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if ret.returncode != 0:
            tooltip = cmd + '\n     ==>    \n' + ret.stderr
            txt = f'commit fail!'
            self.set_label(txt, tooltip)
            return False
        else:
            txt = f'commit done successfull'
            tooltip = cmd + '\n     ==>    \n' + ret.stdout
            self.set_label(txt, tooltip)
            self.ui.msg.setText('')
            return True

    def do_pull(self):
        if not self.pull_lock:
            self.pull_lock = True
            self.get_selected_branch()
            self.check_changes()
            if len(self.change_list) == 0 :
                self.set_label(f"Start pull on branch : {self.selected_branch}")
                cmd = f'cd {self.path} && git pull origin {self.selected_branch}'
                ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if ret.returncode != 0:
                    tooltip = cmd + '\n     ==>    \n' + ret.stderr
                    txt = f'{self.section[0]} : {self.selected_branch} Cannot pull!'
                    self.set_label(txt, tooltip)
                else:
                    txt = f'{self.section[0]} : {self.selected_branch} is up to date'
                    tooltip = cmd + '\n     ==>    \n' + ret.stdout
                    self.set_label(txt, tooltip)
                self.update_branch(label=False)
            else:
                txt = f'commit or delete before pull!'
                tooltip = 'Some change have not been add / commit, you need to do it before pull'
                self.set_label(txt, tooltip)
            self.pull_lock = False

    def do_push(self):
        cmd = f'cd {self.path} && git push origin {self.selected_branch}'
        ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if ret.returncode != 0:
            tooltip = cmd + '\n     ==>    \n' + ret.stderr
            txt = f'push fail!'
            self.set_label(txt, tooltip)
            return False
        else:
            txt = f'push done successfull'
            tooltip = cmd + '\n     ==>    \n' + ret.stdout
            self.set_label(txt, tooltip)
            return True

    def do_add_branch(self,name):
        cmd = f'cd {self.path} && git branch {name}'
        ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if ret.returncode != 0:
            tooltip = cmd + '\n     ==>    \n' + ret.stderr
            txt = f'cannot create branch!'
            self.set_label(txt, tooltip)
            return False
        else:
            txt = f'branch created'
            tooltip = cmd + '\n     ==>    \n' + ret.stdout
            self.set_label(txt, tooltip)
            return True

    def do_make_branch(self,branch):
        self.get_branches()
        if branch not in self.local_branches and branch is not None and branch != '':
            cmd = f'cd {self.path} && git branch {branch}'
            ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if ret.returncode != 0:
                tooltip = cmd + '\n     ==>    \n' + ret.stderr
                txt = 'Cannot make branch!'
                self.set_label(txt, tooltip)
                raise ValueError(txt + '\n' + tooltip)
            else:
                txt = f'branch is made'
                tooltip = cmd + '\n     ==>    \n' + ret.stdout
                self.set_label(txt, tooltip)
            self.update_branch()
        else:
            txt = f'branch already exist!'
            tooltip = f'branch {branch} already exist on local, cannot process do_make_branch()'
            self.set_label(txt, tooltip)

    def set_label(self, txt , tooltip = None):
        self.ui.label.setText(txt)
        if tooltip is not None:
            self.ui.label.setToolTip(tooltip)
        else:
            self.ui.label.setToolTip(txt)

    def get_selected_branch(self):
        path = self.path + '/.git/HEAD'
        if os.path.exists(path):
            file = open(path,'r')
            line = file.readline()
            self.selected_branch = line.split('/')[-1][:-1]
        else:
            self.selected_branch = None

    def get_branches(self):
        branches_path = self.path +  '/.git/refs/heads'
        content = os.listdir(branches_path)
        branches = []
        for i in content:
            p = branches_path + '/' + i
            if os.path.isfile(p):
                branches.append(i)
        self.branches = branches
        self.local_branches = branches

    def get_remotes(self):
        remotes_path = self.path + '/.git/refs/remotes'
        if not os.path.exists(remotes_path):
            self.remotes = None
            return
        content = os.listdir(remotes_path)
        remotes_list = []
        remotes = {}
        for i in content:
            p = remotes_path + '/' + i
            if os.path.isdir(p):
                remotes_list.append(i)

        for i in remotes_list:
            branches_path = self.path + '/.git/refs/remotes/' + i
            content = os.listdir(branches_path)
            branches = []
            for j in content:
                p = branches_path + '/' + j
                if os.path.isfile(p):
                    branches.append(j)
            remotes[i] = branches

        self.remotes = remotes

    def check_changes(self):
        cmd = f'cd {self.path} && git ls-files -m -d -o --exclude-standard'
        ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=False, text=True)
        changes = ret.stdout.split('\n')
        out = []
        for i in changes:
            if i != '':
                out.append(i)
        self.change_list = out

        self.check_cached_changes()

        self.update_changes()

    def update_changes(self):
        self.tree.clear()
        if len(self.change_list) > 0 :
            header = QTreeWidgetItem(self.tree)
            header.setText(0, "---- Modified files ----")
            self.tree_list = []
            for i in self.change_list:
                elmt = QTreeWidgetItem(self.tree)
                elmt.setFlags(elmt.flags() | Qt.ItemIsUserCheckable)
                elmt.setText(0,i)
                elmt.setToolTip(0, i)
                elmt.setCheckState(0, Qt.Unchecked)
                self.tree_list.append(elmt)

        if len(self.cached_change_list) > 0:
            header = QTreeWidgetItem(self.tree)
            header.setText(0, "---- Cached files ----")
            for i in self.cached_change_list:

                elmt = QTreeWidgetItem(self.tree)
                # elmt.setFlags(elmt.flags() | Qt.ItemIsUserCheckable)
                elmt.setText(0, i)
                elmt.setToolTip(0, i)
                # elmt.setCheckState(0, Qt.Unchecked)


            #

    def check_cached_changes(self):
        cmd = f'cd {self.path} && git diff --name-only --cached'
        ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=False, text=True)
        changes = ret.stdout.split('\n')
        out = []
        for i in changes:
            if i != '':
                out.append(i)
        print(out)
        self.cached_change_list = out

    def process_branches(self):
        if self.remotes == None:
            return

        remotes_branches = []
        for i in self.remotes:
            remotes_branches += self.remotes[i]

        branches = [self.selected_branch] + self.branches + remotes_branches

        out = []
        for i in branches:
            if i not in out:
                out.append(i)

        self.branches = out


if __name__ == "__main__":
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setStyle("Fusion")

    # Now use a palette to switch to dark colors:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, Qt.black)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)

    widget = GitHUD()
    widget.setWindowTitle('GitHUD')
    widget.show()

    clipboard = app.clipboard()

    sys.exit(app.exec_())

