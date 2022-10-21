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

        self.os = sys.platform
        if self.os == 'linux':
            self.slash = "/"
        elif self.os == 'windows':
            self.slash = "\\"
        print(f'platform = {self.os}')

        self.ui = None
        self.build_gui()
        self.tree = self.ui.tree
        self.tree_list = []

        if sys.platform == 'win32':
            self.os = "windows"
            self.bash_and = '&'
            self.bash_2_and = '&'
        else:
            self.os ="unix"
            self.bash_and = ";"
            self.bash_2_and = '&&'

        if self.os == "windows":
            self.slash = "\\"
        else:
            self.slash = "/"

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

        self.tree.itemChanged.connect(self.tree_changed)

        self.ui.combo_project.currentTextChanged.connect(self.update_section)
        self.ui.combo_section.currentTextChanged.connect(self.update_branch)
        self.ui.combo_branch.currentTextChanged.connect(self.on_branch_choice)

        self.ui.b_pull.clicked.connect(self.on_pull)
        self.ui.b_push.clicked.connect(self.on_push)
        self.ui.b_commit.clicked.connect(self.on_commit)
        self.ui.b_commit_push.clicked.connect(self.on_commit_push)
        self.ui.b_ignore.clicked.connect(self.on_ignore)
        self.ui.b_merge.clicked.connect(self.on_merge)
        self.ui.b_update.clicked.connect(self.on_update)
        self.ui.b_delete.clicked.connect(self.on_delete_branch)

        self.list_projects()

        self.update_project()

    def tree_changed(self,item,col):
        if len(self.tree_list) > 0:

            if item == self.tree_list[0]:
                if item.checkState(0) == Qt.Checked:
                    self.select_all_changes()
                elif item.checkState(0) != Qt.Checked:
                    self.deselect_all_changes()

    def select_all_changes(self):
        for i in self.tree_list:
            i.setCheckState(0, Qt.Checked)

    def deselect_all_changes(self):
        for i in self.tree_list:
            i.setCheckState(0, Qt.Unchecked)

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
                    a = a.split(self.slash)

                    prj = (self.slash.join(a[:-1])).split(i)
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
        self.sections.sort()
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

    def update_changes(self):
        self.tree.clear()
        if len(self.change_list) > 0 :
            header = QTreeWidgetItem(self.tree)
            header.setText(0, "---- Modified files ----")
            self.tree_list = []
            elmt = QTreeWidgetItem(self.tree)
            elmt.setFlags(elmt.flags() | Qt.ItemIsUserCheckable)
            elmt.setText(0, "-- All --")
            elmt.setCheckState(0, Qt.Unchecked)
            self.tree_list.append(elmt)
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
                elmt.setText(0, i)
                elmt.setToolTip(0, i)

    def on_branch_choice(self):
        print("on_branch_choice()")
        branch = self.ui.combo_branch.currentText()
        print(branch)

        if branch == 'master' or branch == 'main':
            self.ui.b_commit.setVisible(False)
            self.ui.b_commit_push.setVisible(False)
            self.ui.b_ignore.setVisible(False)

        else:
            self.ui.b_commit.setVisible(True)
            self.ui.b_commit_push.setVisible(True)
            self.ui.b_ignore.setVisible(True)

        if branch == '':
            return

        if not branch == '--new--':
            if branch[0] == '<' and branch[-1] == '>':
                branch = branch[1:-1]
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

                if (i.checkState(0) == Qt.CheckState.Checked) and i != self.tree_list[0]:
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

    def on_update(self):
        self.check_changes()
        self.update_changes()

    def on_delete_branch(self):

        branch = self.ui.combo_branch.currentText()
        self.do_delete_branch(branch)

    def do_checkout(self, branch):
        self.get_selected_branch()
        if branch is not None and branch != '' and branch != self.selected_branch:
            checkout = f'cd {self.path} {self.bash_2_and} git commit -m "change_branch" {self.bash_and} git checkout {branch}'
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
        print("do_merge()")

        branch = self.ui.combo_branch.currentText()

        cmd = f'cd {self.path} {self.bash_2_and} git merge {_from}'
        if branch == 'master' or branch == 'main':
            cmd += f' {self.bash_2_and} git branch --delete {_from}'

        print(cmd)
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
            self.update_section()
            return True

    def do_ignore(self,file):

        # quotes marks around filename with spaces make issue w/ gitignore and path.exists()
        if file[0] == "'" and file[-1] == "'":
            file = file[1:-1]

        path = self.path + self.slash + file
        gitignore_path = self.path + self.slash + '.gitignore'
        if not os.path.exists(path):
            txt = f"file don't exist!"
            self.set_label(txt)
            return False

        f = open(gitignore_path, 'a')
        f.write(file +'\n')
        f.close()
        return True

    def do_add(self,file):
        cmd = f'cd {self.path} {self.bash_2_and} git add {file}'
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

        cmd = f'cd {self.path} {self.bash_2_and} git commit -m "{msg}"'
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
                cmd = f'cd {self.path} {self.bash_2_and} git pull origin {self.selected_branch}'
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
        cmd = f'cd {self.path} {self.bash_2_and} git push origin {self.selected_branch}'
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
        cmd = f'cd {self.path} {self.bash_2_and} git branch {name}'
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
            cmd = f'cd {self.path} {self.bash_2_and} git branch {branch}'
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

    def do_delete_branch(self, branch):

        if branch != 'master' and branch != 'main':
            cmd = f'cd {self.path} {self.bash_2_and} git checkout master {self.bash_2_and} git branch -D {branch}'
            ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if ret.returncode != 0:
                tooltip = cmd + '\n     ==>    \n' + ret.stderr
                txt = 'Cannot delete branch!'
                self.set_label(txt, tooltip)
                raise ValueError(txt + '\n' + tooltip)
            else:
                txt = f'{branch} deleted'
                tooltip = cmd + '\n     ==>    \n' + ret.stdout
                self.set_label(txt, tooltip)
            self.update_branch()
        else:
            txt = f'cannot delete master/main!'
            self.set_label(txt)

    def set_label(self, txt , tooltip = None):
        self.ui.label.setText(txt)
        if tooltip is not None:
            self.ui.label.setToolTip(tooltip)
        else:
            self.ui.label.setToolTip(txt)

    def get_selected_branch(self):
        path = self.path + self.slash +'.git' + self.slash +'HEAD'
        if os.path.exists(path):
            file = open(path,'r')
            line = file.readline()
            self.selected_branch = line.split('/')[-1][:-1]
        else:
            self.selected_branch = None

    def get_branches(self):
        branches_path = self.path +  self.slash + '.git' + self.slash +'refs' + self.slash + 'heads'
        content = os.listdir(branches_path)
        branches = []
        for i in content:
            p = branches_path + self.slash + i
            if os.path.isfile(p):
                branches.append(i)
        self.branches = branches
        self.local_branches = branches

    def get_remotes(self):
        print('get_remotes()')
        remotes_path = self.path + self.slash +'.git' + self.slash +'refs'+ self.slash +'remotes'
        if not os.path.exists(remotes_path):
            self.remotes = None
            return
        content = os.listdir(remotes_path)
        remotes_list = []
        remotes = {}
        for i in content:
            p = remotes_path + self.slash + i
            if os.path.isdir(p):
                remotes_list.append(i)

        for i in remotes_list:
            branches_path = self.path + self.slash +'.git' + self.slash + 'refs' + self.slash +'remotes' + self.slash + i
            content = os.listdir(branches_path)
            branches = []
            for j in content:
                p = branches_path + self.slash + j
                if os.path.isfile(p) and j != 'HEAD':
                    branches.append(j)
            remotes[i] = branches
        print(remotes)
        self.remotes = remotes

    def check_changes(self):
        # print("check_changes()")
        cmd = f'cd {self.path} {self.bash_2_and} git ls-files -m -d -o --exclude-standard'
        ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=False, text=True)

        changes = ret.stdout.split('\n')
        out = []
        for i in changes:
            is_lock = False
            is_ignored = False

            # hide libreoffice lock files
            if i.split(self.slash)[-1][:6] == '.~lock':
                is_lock = True

            # hide zw3d back files
            if i.split(self.slash)[-1][-6:] == '.z3bak':
                is_lock = True

            # hide back files
            if i.split(self.slash)[-1][-4:] == '.bak':
                is_lock = True

            # hide winrelais back files
            if i.split(self.slash)[-1][-4:] == '.xrs' and 'Sauvegarde' in i:
                is_lock = True

            # hide githud shortcut
            if i.split(self.slash)[-1] == 'githud.desktop':
                is_lock = True

            # hide githud conf file
            if i.split(self.slash)[-1] == 'user.conf':
                is_lock = True

            # hide githud .gitignore file
            if self.section[0].lower() == 'githud' and i.split(self.slash)[-1] == '.gitignore':
                is_lock = True

            # hide jetbrains config files (Pycharm, CLion, etc....)
            if i.split(self.slash)[0] == '.idea':
                is_ignored = True

            # hide anything in __pycache__ folders
            pth = i.split(self.slash)[:-1]
            for p in pth:
                if p == '__pycache__':
                    is_ignored = True

            # hide python venv folder
            if i.split(self.slash)[0] == 'venv':
                is_ignored = True

            if i != '' and not is_lock and not is_ignored:
                out.append(i)

        out = list(set(out))
        self.change_list = out

        self.check_cached_changes()

        self.update_changes()
        print("--------------")

    def check_cached_changes(self):
        cmd = f'cd {self.path} {self.bash_2_and} git diff --name-only --cached'
        ret = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=False, text=True)
        changes = ret.stdout.split('\n')
        out = []
        for i in changes:
            if i != '':
                out.append(i)
        # print(out)
        self.cached_change_list = out

    def process_branches(self):
        print('process_branches()')
        print(f'selected branch : {self.selected_branch}')
        if self.remotes is None:
            return

        remotes_branches = []
        for i in self.remotes:
            remotes_branches += self.remotes[i]

        out = [self.selected_branch] + self.branches

        # out = []
        for i in remotes_branches:
            if i not in out:
                r_branch = f'<{i}>'
                out.append(r_branch)

        out2 = []
        for i in out:
            if i not in out2:
                out2.append(i)

        print(f'branches:{out2}')

        self.branches = out2


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

