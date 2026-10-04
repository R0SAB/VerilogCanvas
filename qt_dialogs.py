"""Native Qt property editors. Dialog buttons stay outside scrolling editors."""
import copy
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QDialogButtonBox,
    QPlainTextEdit, QLineEdit, QLabel, QTabWidget, QWidget, QPushButton, QComboBox,
    QSpinBox, QMessageBox, QFileDialog, QInputDialog)
from model import Document, Port, identifier, expression, DesignError
from hdl_import import load_modules
from inline_hdl import parse_inline, update_interface


def code_editor(value):
    box=QPlainTextEdit(value);box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    f=QFont('Consolas',11);f.setStyleHint(QFont.StyleHint.Monospace);box.setFont(f)
    box.setTabStopDistance(box.fontMetrics().horizontalAdvance(' ')*4)
    return box


class Dialog(QDialog):
    def __init__(self,parent,title,width=760,height=500):
        super().__init__(parent);self.setWindowTitle(title);self.resize(width,height)
        self.setMinimumSize(min(width,440),min(height,280));self.value=None
        self.layout=QVBoxLayout(self);self.layout.setContentsMargins(16,16,16,16)
        self.shortcut=QShortcut(QKeySequence('Ctrl+Return'),self);self.shortcut.activated.connect(self.accept)

    def hint(self,value):
        label=QLabel(value);label.setWordWrap(True);self.layout.addWidget(label);return label

    def buttons(self):
        self.button_box=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText('Apply')
        self.button_box.accepted.connect(self.accept);self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def showEvent(self,event):
        super().showEvent(event)
        if not getattr(self,'centered',False):
            parent=self.parentWidget();area=parent.centralWidget() if hasattr(parent,'centralWidget') else parent
            center=area.mapToGlobal(area.rect().center());screen=self.screen().availableGeometry()
            x=max(screen.left(),min(center.x()-self.width()//2,screen.right()-self.width()))
            y=max(screen.top(),min(center.y()-self.height()//2,screen.bottom()-self.height()))
            self.move(x,y);self.centered=True

    def error(self,exc):QMessageBox.warning(self,self.windowTitle(),str(exc))


def choose_hdl(parent):
    path,_=QFileDialog.getOpenFileName(parent,'Import Module Interface','','HDL (*.v *.sv);;All files (*)')
    if not path:return None
    try:
        modules=load_modules(path)
        if len(modules)==1:module=modules[0]
        else:
            choices=[f'{m.name} (line {m.line})' for m in modules]
            choice,ok=QInputDialog.getItem(parent,'Select Module','Module to import:',choices,0,False)
            if not ok:return None
            module=modules[choices.index(choice)]
        return module.to_node(),Path(path).suffix.lower()=='.sv'
    except (OSError,ValueError) as exc:QMessageBox.warning(parent,'Could Not Import Module',str(exc))


class EditorDialog(Dialog):
    def __init__(self,parent,node):
        super().__init__(parent,'Module Properties' if node.kind=='module' else 'Top-Level Port',760,560 if node.kind=='module' else 280)
        self.node=copy.deepcopy(node);self.imported_sv=False;self.fields={};self.boxes={}
        form=QFormLayout();self.layout.addLayout(form)
        rows=[('module','Verilog module name',node.module),('name','Instance name',node.name)] if node.kind=='module' else [('port','Port: [type] [range]name [array]',node.ports()[0].label())]
        for key,label,value in rows:
            field=QLineEdit(value);self.fields[key]=field;form.addRow(label,field)
        if node.kind=='module':
            tabs=QTabWidget();self.layout.addWidget(tabs,1)
            for key,title,value in [('inputs','Inputs','\n'.join(p.label() for p in node.inputs)),('outputs','Outputs','\n'.join(p.label() for p in node.outputs)),('params','Parameters','\n'.join(f'{k} = {v}' for k,v in node.params.items())),('transforms','Transforms','\n'.join(f'{k} = {v}' for k,v in node.transforms.items()))]:
                page=QWidget();layout=QVBoxLayout(page)
                hint='One port per line. Example: logic signed [WIDTH-1:0]data' if key in ('inputs','outputs') else 'One parameter per line: NAME = value' if key=='params' else 'Input transforms: mode = ($ == MOD_AM) ? 1 : 0\n$ is the connected signal; leave blank for a direct connection.'
                label=QLabel(hint);label.setWordWrap(True);layout.addWidget(label)
                box=code_editor(value);self.boxes[key]=box;layout.addWidget(box);tabs.addTab(page,title)
        self.buttons()
        if node.kind=='module':
            button=QPushButton('Import .v/.sv…');button.clicked.connect(self.import_interface)
            self.button_box.addButton(button,QDialogButtonBox.ButtonRole.ActionRole)

    def import_interface(self):
        result=choose_hdl(self)
        if result:
            n,self.imported_sv=result;self.fields['module'].setText(n.module)
            for key in ('inputs','outputs','params'):
                self.boxes[key].setPlainText('\n'.join(f'{k} = {v}' for k,v in n.params.items()) if key=='params' else '\n'.join(p.label() for p in getattr(n,key)))

    def accept(self):
        try:
            n=copy.deepcopy(self.node)
            if n.kind=='module':
                n.name=identifier(self.fields['name'].text().strip());n.module=identifier(self.fields['module'].text().strip())
                for key in ('inputs','outputs'):setattr(n,key,[Port.parse(s) for s in self.boxes[key].toPlainText().splitlines() if s.strip()])
                for key in ('params','transforms'):
                    values={}
                    for line in self.boxes[key].toPlainText().splitlines():
                        if not line.strip():continue
                        if '=' not in line:raise DesignError('Expected NAME = value')
                        name,value=line.split('=',1);name=identifier(name.strip())
                        if name in values:raise DesignError('Duplicate name: '+name)
                        values[name]=expression(value) if key=='params' else value.strip()
                    setattr(n,key,values)
            else:
                p=Port.parse(self.fields['port'].text().strip());n.name=p.name
                n.inputs=[p] if n.kind=='output' else [];n.outputs=[p] if n.kind=='input' else []
            n.normalize();Document(top='validation_top' if n.module!='validation_top' else 'validation_other',nodes=[n]).validate()
            self.value=n;super().accept()
        except (ValueError,TypeError) as exc:self.error(exc)


class DeclarationsDialog(Dialog):
    def __init__(self,parent,value):
        super().__init__(parent,'Top-Level Declarations')
        self.hint('HDL after the port list, before nets and instances: typedef, enum, localparam…\nText is inserted as written. Select SystemVerilog for enums. Ctrl+Enter applies changes.')
        self.text=code_editor(value);self.layout.addWidget(self.text,1);self.buttons()
    def accept(self):self.value=self.text.toPlainText();super().accept()


class InlineDialog(Dialog):
    def __init__(self,parent,node):
        super().__init__(parent,'Inline HDL Block',820,600);self.node=copy.deepcopy(node);self.imported_sv=False
        form=QFormLayout();self.name=QLineEdit(node.name);form.addRow('Block name',self.name);self.layout.addLayout(form)
        self.hint('Declare input/output ports, then write the HDL body. Ports are generated on Apply.\nShared top-level scope: code and names are preserved. Do not add a module wrapper.')
        self.text=code_editor(node.hdl_source);self.layout.addWidget(self.text,1)
        self.summary=self.hint('Interface checks do not replace compilation by your HDL tools.')
        self.buttons();button=QPushButton('Check Ports');button.clicked.connect(self.check_ports)
        self.button_box.addButton(button,QDialogButtonBox.ButtonRole.ActionRole)
    def check_ports(self):
        try:
            interface=parse_inline(self.text.toPlainText())
            self.summary.setText('Inputs: '+(', '.join(p.label() for p in interface.inputs) or 'none')+'\nOutputs: '+(', '.join(p.label() for p in interface.outputs) or 'none'))
        except ValueError as exc:self.error(exc)
    def accept(self):
        try:
            n=copy.deepcopy(self.node);n.name=identifier(self.name.text().strip())
            interface=update_interface(n,self.text.toPlainText());self.imported_sv=interface.requires_sv
            self.value=n;super().accept()
        except ValueError as exc:self.error(exc)


class PortMappingDialog(Dialog):
    def __init__(self,parent,old,new,removed):
        super().__init__(parent,'Reconnect Inline HDL Ports',600,320);self.fields={}
        self.hint('Connected ports were removed or changed direction. Choose replacement ports, or disconnect their wires.')
        form=QFormLayout();self.layout.addLayout(form)
        retained={p.name for p in old.ports() if p.name not in removed}
        for name in removed:
            box=QComboBox();box.addItems(['(disconnect)']+[p.name for p in new.ports() if p.name not in retained and new.source(p.name)==old.source(name)])
            self.fields[name]=box;form.addRow(('Output ' if old.source(name) else 'Input ')+name,box)
        self.buttons()
    def accept(self):
        values={k:None if v.currentIndex()==0 else v.currentText() for k,v in self.fields.items()}
        mapped=[v for v in values.values() if v is not None]
        if len(mapped)!=len(set(mapped)):self.error('Each replacement port can be used only once.');return
        self.value=values;super().accept()


class CommentDialog(Dialog):
    def __init__(self,parent,comment):
        super().__init__(parent,'Comment Properties',620,400);self.comment=copy.deepcopy(comment)
        self.kind=QComboBox();self.kind.addItems(['Text comment','Group comment']);self.kind.setCurrentIndex(comment.kind=='group');self.layout.addWidget(self.kind)
        self.hint('Text: schematic only. Group: contains objects and adds an HDL section heading.')
        self.text=code_editor(comment.text);self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth);self.layout.addWidget(self.text,1)
        form=QFormLayout();self.size=QSpinBox();self.size.setRange(8,32);self.size.setValue(comment.font_size);form.addRow('Font size',self.size);self.layout.addLayout(form);self.buttons()
    def accept(self):
        try:
            c=copy.deepcopy(self.comment);c.text=self.text.toPlainText();c.kind='group' if self.kind.currentIndex() else 'text';c.font_size=self.size.value();c.validate();self.value=c;super().accept()
        except ValueError as exc:self.error(exc)


class PreviewDialog(Dialog):
    def __init__(self,parent,source):
        super().__init__(parent,'HDL Preview',900,680)
        box=code_editor(source);box.setReadOnly(True);self.layout.addWidget(box)
        button=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);button.rejected.connect(self.reject);self.layout.addWidget(button)
