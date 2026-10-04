"""Qt performance preview. Uses the production model without importing Tkinter.

Persistent scene objects; geometry-only updates during drag. Net checks run on
load / completed edits, never on navigation or paint. See QT_PREVIEW.md.
"""
import copy
import math
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF, QLineF, QTimer
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetricsF, QPainter,
                          QPainterPath, QPainterPathStroker, QPen, QPolygonF,
                          QKeySequence, QBrush, QPixmap, QTransform)
from PySide6.QtWidgets import (QApplication, QMainWindow, QGraphicsScene,
                              QGraphicsView, QGraphicsItem, QFileDialog,
                              QMessageBox, QToolBar, QLabel, QComboBox)
from model import (Document, GRID, COORD_LIMIT, route, snap, nearest_segment,
                   junction_point, path_position, project_to_path)

BG='#101722'; PANEL='#1a2636'; TEXT='#e4eefb'; BLUE='#52b6ff'
PORT='#a99be8'; MUTED='#9099a8'; GREEN='#65ed8a'; ERROR='#ff6262'
AMBER='#ffd47e'; LABEL='#86dac8'
LEFT=Qt.AlignmentFlag.AlignLeft; RIGHT=Qt.AlignmentFlag.AlignRight
CENTER=Qt.AlignmentFlag.AlignHCenter; VCENTER=Qt.AlignmentFlag.AlignVCenter
NO_BRUSH=Qt.BrushStyle.NoBrush; NO_PEN=Qt.PenStyle.NoPen


def font(size=10,bold=False):
    f=QFont('Consolas');f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(round(size*4/3));f.setBold(bold);return f


def pen(color,width=1,dashed=False):
    p=QPen(QColor(color),width)
    if dashed:p.setStyle(Qt.PenStyle.DashLine)
    return p


def text(p,rect,value,size=10,color=TEXT,bold=False,align=LEFT,wrap=False):
    f=font(size,bold);p.setFont(f);p.setPen(QColor(color))
    flags=align|Qt.AlignmentFlag.AlignTop if wrap else align|VCENTER
    if wrap:flags|=Qt.TextFlag.TextWordWrap
    else:value=QFontMetricsF(f).elidedText(value,Qt.TextElideMode.ElideRight,max(0,rect.width()))
    p.drawText(rect,flags,value)


def poly(points):return QPolygonF([QPointF(x,y) for x,y in points])


class SceneItem(QGraphicsItem):
    def __init__(self,owner,kind,key):
        super().__init__();self.owner=owner;self.kind=kind;self.key=key
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True);self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.rect=QRectF()

    def boundingRect(self):return self.rect

    def mousePressEvent(self,event):
        self.owner.begin_drag(self,event.scenePos(),event.modifiers());event.accept()

    def mouseMoveEvent(self,event):
        self.owner.move_drag(event.scenePos());event.accept()

    def mouseReleaseEvent(self,event):
        self.owner.finish_drag();event.accept()

    def mouseDoubleClickEvent(self,event):
        self.owner.statusBar().showMessage('Preview: property editing is not implemented yet.',4000)
        event.accept()


class NodeItem(SceneItem):
    def __init__(self,owner,node):
        super().__init__(owner,'node',node.id);self.n=node;self.setZValue(10)
        self.labels=[];self.setToolTip(f'{node.name}\n{node.module if node.kind=="module" else node.kind}')
        # Resolve parameter expressions only when constructing the item.
        for port in node.ports():
            packed,unpacked=port.dimensions_text(node.params)
            detail=('bit ' if port.two_state else '')+('signed ' if port.signed else '')+packed+unpacked
            self.labels.append((port.name,detail,node.source(port.name)))
        self.rect=QRectF(-312 if node.transforms else -7,-7,
                         node.w+(319 if node.transforms else 14),node.h+14)
        self.sync_position()

    def sync_position(self):self.setPos(self.n.x,self.n.y)

    def shape(self):
        p=QPainterPath();n=self.n
        if n.kind in ('input','output'):
            left=0 if n.kind=='input' else 40;right=n.w-40 if n.kind=='input' else n.w
            p.addRect(QRectF(left,40,right-left,40))
        else:p.addRect(QRectF(0,0,n.w,n.h))
        for name,detail,out in self.labels:
            x,y=n.endpoint(name);p.addEllipse(QPointF(x-n.x,y-n.y),7,7)
        return p

    def paint(self,p,option,widget=None):
        n=self.n;selected=self.isSelected();outline=GREEN if selected else '#e79543' if n.kind=='inline' else '#435874'
        if n.kind in ('input','output'):
            left=0 if n.kind=='input' else 40;right=n.w-40 if n.kind=='input' else n.w
            p.setPen(pen(GREEN if selected else PORT,2));p.setBrush(QColor(PANEL))
            p.drawPolygon(poly([(left,40),(right-20,40),(right,60),(right-20,80),(left,80)]))
            x,y=n.endpoint(n.name);x-=n.x;y-=n.y
            p.drawLine(QLineF(right if n.kind=='input' else 0,60,x if n.kind=='input' else left,60))
            detail=self.labels[0][1];width=right-left-28;cx=left+(right-left-20)/2
            text(p,QRectF(cx-width/2,44 if detail else 48,width,24),n.name,11,BLUE,True,CENTER)
            if detail:text(p,QRectF(cx-width/2,63,width,15),detail,9,MUTED,align=CENTER)
            p.setPen(pen(BG));p.setBrush(QColor(ERROR if (n.id,n.name) in self.owner.bad_ports else PORT));p.drawEllipse(QPointF(x,y),5,5)
            return
        p.setPen(NO_PEN);p.setBrush(QColor('#38281d' if n.kind=='inline' else PANEL));p.drawRect(QRectF(0,0,n.w,n.h))
        p.setBrush(QColor('#80491e' if n.kind=='inline' else '#23354a'));p.drawRect(QRectF(0,0,n.w,36))
        p.setPen(pen(outline,2 if selected else 1));p.setBrush(NO_BRUSH);p.drawRect(QRectF(0,0,n.w,n.h))
        text(p,QRectF(10,6,n.w-20,24),'Inline HDL' if n.kind=='inline' else n.module,11,TEXT,True)
        for name,detail,out in self.labels:
            x,y=n.endpoint(name);x-=n.x;y-=n.y;tw=n.w/2-22
            tx=x-12-tw if out else x+12;align=RIGHT if out else LEFT
            text(p,QRectF(tx,y-17 if detail else y-10,tw,20),name,10,BLUE,align=align)
            if detail:text(p,QRectF(tx,y+2,tw,17),detail,9,MUTED,align=align)
            if name in n.transforms:text(p,QRectF(x-310,y+4,300,18),n.transforms[name],9,AMBER,align=RIGHT)
            p.setPen(pen(BG));p.setBrush(QColor(ERROR if (n.id,name) in self.owner.bad_ports else BLUE));p.drawEllipse(QPointF(x,y),5,5)
        if n.params:
            top=n.parameters_y()-n.y;p.setPen(pen('#35465b'));p.drawLine(QLineF(12,top-10,n.w-12,top-10))
            for i,(key,value) in enumerate(n.params.items()):text(p,QRectF(12,top+i*20-2,n.w-24,20),f'{key} = {value}',10,'#d5dceb')
        text(p,QRectF(12,n.h-27,n.w-24,22),n.name,10,MUTED,align=CENTER)
        if selected:
            p.setBrush(QColor(GREEN));p.setPen(pen(BG))
            for x,y in ((0,0),(n.w,0),(0,n.h),(n.w,n.h)):p.drawRect(QRectF(x-4,y-4,8,8))

    def hoverMoveEvent(self,event):
        n=self.n;point=event.pos();hint=f'{n.name} — {n.module if n.kind=="module" else n.kind}'
        for name,detail,out in self.labels:
            x,y=n.endpoint(name)
            if abs(point.y()-(y-n.y))<18:
                hint=f'{n.name}.{name} {detail}'
                if name in n.transforms:hint+='\nTransform: '+n.transforms[name]
                errors=self.owner.bad_ports.get((n.id,name),[])
                if errors:hint+='\n'+'\n'.join(errors)
                break
        self.setToolTip(hint)


class CommentItem(SceneItem):
    def __init__(self,owner,comment):
        super().__init__(owner,'comment',comment.id);self.c=comment
        self.group=comment.kind=='group';self.setZValue(30 if self.group else 12)
        margin=12 if self.group else 0;width=comment.w-2*margin
        metrics=QFontMetricsF(font(comment.font_size))
        self.caption=metrics.boundingRect(QRectF(0,0,width,100000),Qt.TextFlag.TextWordWrap,comment.text)
        self.height=comment.h if self.group else max(comment.h,self.caption.height())
        self.rect=QRectF(-7,-7,comment.w+14,max(self.height,self.caption.height()+16)+14)
        self.setPos(comment.x,comment.y);self.setToolTip(comment.text)

    def shape(self):
        p=QPainterPath();c=self.c
        if self.group:
            outline=QPainterPath();outline.addRect(QRectF(0,0,c.w,c.h));stroke=QPainterPathStroker();stroke.setWidth(10);p=stroke.createStroke(outline)
            p.addRect(QRectF(12,8,c.w-24,self.caption.height()))
        else:p.addRect(QRectF(0,0,c.w,self.height))
        return p

    def paint(self,p,option,widget=None):
        c=self.c;selected=self.isSelected()
        if self.group or selected:
            p.setBrush(NO_BRUSH);p.setPen(pen(AMBER if self.group and selected else GREEN if selected else '#899baf',1,True))
            p.drawRect(QRectF(0,0,c.w,c.h if self.group else self.height))
        inset=12 if self.group else 0
        text(p,QRectF(inset,8 if self.group else 0,c.w-2*inset,self.caption.height()+4),c.text,c.font_size,'#daca9d',wrap=True)


class WireItem(SceneItem):
    def __init__(self,owner,wire):
        super().__init__(owner,'wire',wire.id);self.w=wire;self.setZValue(0)
        self.path=QPainterPath();self.hit_path=QPainterPath();self.points=[];self.loose=[];self.joint=None
        self.refresh()

    def refresh(self):
        points=route(self.owner.doc,self.w);path=QPainterPath()
        if points:
            path.moveTo(*points[0])
            for point in points[1:]:path.lineTo(*point)
        self.prepareGeometryChange();self.points=points;self.path=path
        stroke=QPainterPathStroker();stroke.setWidth(12);self.hit_path=stroke.createStroke(path)
        self.loose=self.w.loose_ends();self.joint=junction_point(self.owner.doc,self.w) if self.w.join_wire else None
        for _,point in self.loose:self.hit_path.addEllipse(QPointF(*point),8,8)
        if self.joint:self.hit_path.addEllipse(QPointF(*self.joint),8,8)
        self.rect=self.hit_path.boundingRect().adjusted(-2,-2,2,2);self.update()

    def shape(self):return self.hit_path

    def paint(self,p,option,widget=None):
        bus=self.owner.widths.get(self.key,self.w.width_hint)>1
        color=GREEN if self.isSelected() else BLUE if bus else '#a8c4df'
        p.setBrush(NO_BRUSH);p.setPen(pen(color,4 if bus else 1.5));p.drawPath(self.path)
        if self.joint:
            p.setPen(pen(BG));p.setBrush(QColor(color));p.drawEllipse(QPointF(*self.joint),5,5)
        for _,point in self.loose:
            p.setPen(pen(ERROR if self.key in self.owner.bad_wires else color,2));p.setBrush(QColor(BG));p.drawEllipse(QPointF(*point),5,5)

    def hoverMoveEvent(self,event):
        point=event.scenePos();i=nearest_segment(self.points,point.x(),point.y())
        floating=self.key in self.owner.floating
        self.setCursor(Qt.CursorShape.SizeAllCursor if floating else Qt.CursorShape.SizeVerCursor if self.points[i][1]==self.points[i+1][1] else Qt.CursorShape.SizeHorCursor)
        self.setToolTip('\n'.join(self.owner.bad_wires.get(self.key,[])) or ('Drag to move the detached wire' if floating else 'Drag segment; drag an open circle to move its endpoint'))


class LabelItem(SceneItem):
    def __init__(self,owner,label):
        super().__init__(owner,'label',label.id);self.label=label;self.setZValue(20)
        width=QFontMetricsF(font(10,True)).horizontalAdvance(label.name)
        self.rect=QRectF(-4,-27,width+20,32);self.refresh();self.setToolTip(label.name)

    def refresh(self):self.setPos(*path_position(self.owner.wire_items[self.label.wire_id].points,self.label.position))

    def paint(self,p,option,widget=None):
        color=GREEN if self.isSelected() else LABEL
        box=QRectF(3,-26,self.rect.width()-7,22)
        p.setPen(pen(color) if self.isSelected() else NO_PEN);p.setBrush(NO_BRUSH);p.drawRect(box)
        text(p,QRectF(7,-25,self.rect.width()-14,20),self.label.name,10,color,True)
        p.setPen(pen(color,1.5));p.drawPolyline(poly([(0,0),(0,-5),(5,-5)]))
        p.setPen(NO_PEN);p.setBrush(QColor(color));p.drawEllipse(QPointF(0,0),3,3)


class DiagramView(QGraphicsView):
    def __init__(self,owner,scene):
        super().__init__(scene);self.owner=owner;self.pan=None;self.paint_samples=deque(maxlen=1000)
        self.grid_mode='Dots';self.grid_tiles={};self.grid_tile_builds=0
        self.setRenderHints(QPainter.RenderHint.Antialiasing|QPainter.RenderHint.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor(BG));self.setMouseTracking(True)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheBackground)

    def set_grid_mode(self,mode):
        if mode not in ('Dots','Lines','Off'):return
        self.grid_mode=mode;self.resetCachedContent();self.viewport().update()

    def dot_brush(self):
        zoom=max(.01,self.transform().m11());dpr=self.viewport().devicePixelRatioF()
        # Coarsen the visible grid at low zoom only; model snapping stays at 20.
        step=GRID*2**max(0,math.ceil(math.log2(6/(GRID*zoom))))
        period=step*5;pixels=max(1,math.ceil(period*zoom*dpr))
        key=(step,pixels,round(dpr,4))
        if key not in self.grid_tiles:
            tile=QPixmap(pixels,pixels);tile.fill(QColor(BG));p=QPainter(tile)
            p.setRenderHint(QPainter.RenderHint.Antialiasing,False)
            for ix in range(6):
                for iy in range(6):
                    # Draw the shared border on both edges of the repeating tile.
                    major=ix%5==0 and iy%5==0
                    p.setPen(pen('#526780' if major else '#35465b',max(1,round(dpr))))
                    p.drawPoint(QPointF(round(ix*pixels/5),round(iy*pixels/5)))
            p.end();brush=QBrush(tile)
            brush.setTransform(QTransform.fromScale(period/pixels,period/pixels))
            if len(self.grid_tiles)>=8:self.grid_tiles.pop(next(iter(self.grid_tiles)))
            self.grid_tiles[key]=brush;self.grid_tile_builds+=1
        return self.grid_tiles[key]

    def drawBackground(self,p,rect):
        p.save()
        # Smoothing the grid adds cost without helping text or wire quality.
        p.setRenderHint(QPainter.RenderHint.Antialiasing,False)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,False)
        if self.grid_mode=='Dots':
            p.setBrushOrigin(QPointF(0,0));p.fillRect(rect,self.dot_brush())
        else:
            p.fillRect(rect,QColor(BG))
            if self.grid_mode=='Lines':
                zoom=max(.01,self.transform().m11());step=GRID*max(1,math.ceil(5/(GRID*zoom)))
                left=math.floor(rect.left()/step)*step;top=math.floor(rect.top()/step)*step
                lines={0:[],1:[],2:[]}
                for x in range(left,math.ceil(rect.right()),step):lines[2 if x==0 else 1 if x%100==0 else 0].append(QLineF(x,rect.top(),x,rect.bottom()))
                for y in range(top,math.ceil(rect.bottom()),step):lines[2 if y==0 else 1 if y%100==0 else 0].append(QLineF(rect.left(),y,rect.right(),y))
                for level,color in enumerate(('#1b2737','#263346','#405774')):
                    q=pen(color);q.setCosmetic(True);p.setPen(q);p.drawLines(lines[level])
        p.restore()

    def set_zoom(self,value,anchor=None):
        value=max(.05,min(4.,value));anchor=anchor or self.viewport().rect().center()
        before=self.mapToScene(anchor);self.scale(value/self.transform().m11(),value/self.transform().m11())
        after=self.mapToScene(anchor);delta=before-after
        self.centerOn(self.mapToScene(self.viewport().rect().center())+delta);self.owner.update_metrics()

    def wheelEvent(self,event):
        if self.owner.drag:event.accept();return
        if event.modifiers()&Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.transform().m11()*1.15**(event.angleDelta().y()/120),event.position().toPoint())
        else:
            bar=self.horizontalScrollBar() if event.modifiers()&Qt.KeyboardModifier.ShiftModifier else self.verticalScrollBar()
            delta=event.pixelDelta().y() if not event.pixelDelta().isNull() else event.angleDelta().y()
            bar.setValue(bar.value()-delta)
        event.accept()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.MiddleButton:
            if self.owner.drag:return
            self.pan=event.position();self.setCursor(Qt.CursorShape.ClosedHandCursor);event.accept();return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.pan is not None:
            delta=event.position()-self.pan;self.pan=event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-round(delta.y()))
            event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.MiddleButton:
            self.pan=None;self.unsetCursor();event.accept();return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.owner.cancel_drag();event.accept();return
        super().keyPressEvent(event)

    def paintEvent(self,event):
        start=time.perf_counter();super().paintEvent(event)
        self.paint_samples.append((time.perf_counter(),(time.perf_counter()-start)*1000))


class Window(QMainWindow):
    def __init__(self):
        super().__init__();self.resize(1360,860);self.doc=Document();self.path=None;self.saved=self.doc.serialize()
        self.history=[];self.future=[];self.drag=None;self.net_checks=0
        self.scene=QGraphicsScene(self);self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.BspTreeIndex)
        self.view=getattr(self,"view_class",DiagramView)(self,self.scene);self.setCentralWidget(self.view)
        self.node_items={};self.comment_items={};self.wire_items={};self.label_items={}
        self.bad_ports={};self.bad_wires={};self.widths={};self.floating=set()
        self.build_toolbar()
        self.metrics=QLabel();self.statusBar().addPermanentWidget(self.metrics)
        self.statusBar().showMessage('Open an existing .vsch. Ctrl+wheel: zoom. Middle drag: pan. Drag objects to compare responsiveness.')
        self.timer=QTimer(self);self.timer.timeout.connect(self.update_metrics);self.timer.start(500)
        self.rebuild();self.update_title()

    def build_toolbar(self):
        toolbar=QToolBar('Preview tools');toolbar.setMovable(False);self.addToolBar(toolbar)
        def action(label,fn,shortcut=None):
            a=QAction(label,self);a.triggered.connect(fn)
            if shortcut:a.setShortcut(QKeySequence(shortcut))
            toolbar.addAction(a);return a
        action('Open…',self.open_dialog,'Ctrl+O');action('Save Copy As…',self.save_copy,'Ctrl+Shift+S');toolbar.addSeparator()
        self.undo_action=action('Undo',self.undo,'Ctrl+Z');self.redo_action=action('Redo',self.redo,'Ctrl+Y');toolbar.addSeparator()
        action('−',lambda:self.view.set_zoom(self.view.transform().m11()/1.2))
        action('+',lambda:self.view.set_zoom(self.view.transform().m11()*1.2))
        action('100%',lambda:self.view.set_zoom(1));action('Fit Diagram',self.fit,'Home');toolbar.addSeparator()
        toolbar.addWidget(QLabel(' Grid: '))
        self.grid_choice=QComboBox();self.grid_choice.addItems(['Dots','Lines','Off'])
        self.grid_choice.currentTextChanged.connect(self.view.set_grid_mode);toolbar.addWidget(self.grid_choice)
        toolbar.addSeparator();action('About Preview',self.about)

    def update_title(self):
        dirty=self.doc.serialize()!=self.saved
        self.setWindowTitle(f'{"* " if dirty else ""}{self.path.name if self.path else "No schematic"} — VerilogCanvas Qt Preview 0.2')
        self.undo_action.setEnabled(bool(self.history));self.redo_action.setEnabled(bool(self.future))

    def update_metrics(self):
        samples=self.view.paint_samples;recent=[duration for stamp,duration in samples if time.perf_counter()-stamp<1]
        timing=f' | paint {sum(recent)/len(recent):.1f} ms | {len(recent)} updates/s' if recent else ''
        self.metrics.setText(f'{len(self.doc.nodes)} blocks / {len(self.doc.wires)} wires | {self.view.transform().m11()*100:.0f}%{timing}')

    def index_model(self):
        self.nodes={n.id:n for n in self.doc.nodes};self.wires={w.id:w for w in self.doc.wires}
        self.comments={c.id:c for c in self.doc.comments}
        self.node_wires=defaultdict(set);self.children=defaultdict(set);self.wire_labels=defaultdict(set)
        for w in self.doc.wires:
            for ep in w.endpoints():self.node_wires[ep[0]].add(w.id)
            if w.join_wire:self.children[w.join_wire].add(w.id)
        for label in self.doc.labels:self.wire_labels[label.wire_id].add(label.id)
        self.groups=self.doc.module_groups();self.comment_groups=self.doc.comment_groups()
        self.net_checks+=1;issues=[];nets=self.doc.nets(strict=False,issues=issues)
        self.bad_ports={};self.bad_wires={};self.widths={}
        for issue in issues:
            for ep in issue['ports']:self.bad_ports.setdefault(tuple(ep),[]).append(issue['message'])
            for wid in issue['wires']:self.bad_wires.setdefault(wid,[]).append(issue['message'])
        for net in nets:
            ep=net.source or (net.ports[0] if net.ports else None)
            width=None
            if ep:n,p=self.doc.resolve(ep);width=p.width(n.params)
            for wid in net.wires:self.widths[wid]=width or self.wires[wid].width_hint
        self.floating=set()
        for w in self.doc.wires:
            if not w.endpoints():self.floating.update(self.doc.floating_wires(w.id))

    def rebuild(self):
        self.scene.clear();self.node_items={};self.comment_items={};self.wire_items={};self.label_items={}
        self.index_model()
        for w in self.doc.wires:
            item=getattr(self,"wire_class",WireItem)(self,w);self.wire_items[w.id]=item;self.scene.addItem(item)
        for n in self.doc.nodes:
            item=getattr(self,"node_class",NodeItem)(self,n);self.node_items[n.id]=item;self.scene.addItem(item)
        for c in self.doc.comments:
            item=getattr(self,"comment_class",CommentItem)(self,c);self.comment_items[c.id]=item;self.scene.addItem(item)
        for label in self.doc.labels:
            item=getattr(self,"label_class",LabelItem)(self,label);self.label_items[label.id]=item;self.scene.addItem(item)
        self.expand_scene();self.update_metrics()

    def expand_scene(self):
        bounds=self.scene.itemsBoundingRect();self.scene.setSceneRect(bounds.adjusted(-100000,-100000,100000,100000))

    def fit(self):
        bounds=self.scene.itemsBoundingRect()
        if not bounds.isEmpty():self.view.fitInView(bounds.adjusted(-40,-40,40,40),Qt.AspectRatioMode.KeepAspectRatio)
        self.update_metrics()

    def affected_wires(self,members,wires):
        result=set(wires)
        for nid in members:result.update(self.node_wires[nid])
        while True:
            expanded=result|{child for wid in result for child in self.children[wid]}
            if expanded==result:return result
            result=expanded

    def refresh_geometry(self,members=(),comments=(),wires=()):
        for nid in members:self.node_items[nid].sync_position()
        for cid in comments:
            c=self.comments[cid];self.comment_items[cid].setPos(c.x,c.y)
        affected=self.affected_wires(members,wires)
        for wid in affected:self.wire_items[wid].refresh()
        for wid in affected:
            for lid in self.wire_labels[wid]:self.label_items[lid].refresh()

    def begin_drag(self,item,point,modifiers):
        if self.drag:return
        ctrl=bool(modifiers&Qt.KeyboardModifier.ControlModifier)
        if ctrl or not item.isSelected():self.scene.clearSelection();item.setSelected(True)
        d=dict(before=self.doc.serialize(),point=QPointF(point),offset=(0,0),item=item,kind=item.kind)
        if item.kind in ('node','comment'):
            members={i.key for i in self.scene.selectedItems() if i.kind=='node'}
            comments={i.key for i in self.scene.selectedItems() if i.kind=='comment'}
            selected_wires={i.key for i in self.scene.selectedItems() if i.kind=='wire'}
            if not ctrl:
                groups={self.groups[n] for n in members if n in self.groups}
                groups.update(c for c in comments if self.comments[c].kind=='group')
                groups.update(self.comment_groups[c] for c in comments if c in self.comment_groups)
                for gid in groups:
                    members.update(nid for nid,g in self.groups.items() if g==gid)
                    comments.add(gid);comments.update(cid for cid,g in self.comment_groups.items() if g==gid)
            wires=self.doc.internal_wires(members)|selected_wires
            d.update(kind='objects',members=members,comments=comments,wires=wires)
        elif item.kind=='label':d.update(anchor=QPointF(item.pos()))
        elif item.kind=='wire':
            wire=item.w;side=next((side for side,p in item.loose if (QPointF(*p)-point).manhattanLength()<10),None)
            if side:d.update(kind='end',side=side,anchor=tuple(dict(wire.loose_ends())[side]))
            elif item.key in self.floating:d.update(kind='objects',members=set(),comments=set(),wires=self.doc.floating_wires(item.key))
            else:
                self.doc.freeze_wire(wire)
                d.update(kind='segment',index=nearest_segment(item.points,point.x(),point.y()),original=copy.deepcopy(wire.vertices),host=copy.deepcopy(self.wires[wire.join_wire].vertices) if wire.join_wire else None)
        self.drag=d

    def move_drag(self,point):
        d=self.drag
        if not d:return
        delta=point-d['point'];offset=(snap(delta.x()),snap(delta.y()));item=d['item']
        try:
            if d['kind']=='objects':
                dx,dy=offset[0]-d['offset'][0],offset[1]-d['offset'][1]
                if not(dx or dy):return
                self.doc.move_objects(d['members'],d['comments'],d['wires'],dx,dy)
                self.refresh_geometry(d['members'],d['comments'],d['wires'])
            elif d['kind']=='end':
                item.w.set_loose(d['side'],[d['anchor'][0]+offset[0],d['anchor'][1]+offset[1]])
                self.refresh_geometry(wires={item.key})
            elif d['kind']=='segment':
                wire=item.w
                if d['host'] is not None:self.wires[wire.join_wire].vertices=copy.deepcopy(d['host'])
                self.doc.move_segment(wire,d['index'],*offset,d['original'])
                self.refresh_geometry(wires={item.key}|({wire.join_wire} if wire.join_wire else set()))
            elif d['kind']=='label':
                anchor=d['anchor']+delta;wire=self.wire_items[item.label.wire_id]
                item.label.position=project_to_path(wire.points,anchor.x(),anchor.y())[0];item.refresh()
            d['offset']=offset
        except Exception as exc:
            self.cancel_drag();QMessageBox.warning(self,'Move cancelled',str(exc))

    def finish_drag(self):
        if not self.drag:return
        d=self.drag;self.drag=None
        try:
            changed=self.doc.serialize()!=d['before']
            if changed and d['kind']!='label':self.doc.attach_coincident()
            self.doc.validate(electrical=False)
        except Exception as exc:
            self.doc=Document.deserialize(d['before']);self.rebuild();QMessageBox.warning(self,'Move cancelled',str(exc));return
        if self.doc.serialize()!=d['before']:
            self.history.append(d['before']);self.history=self.history[-100:];self.future=[]
            self.index_model();self.refresh_geometry(wires=self.wires)
            for item in self.node_items.values():item.update()
            self.expand_scene()
        self.update_title()

    def cancel_drag(self):
        if self.drag:
            state=self.drag['before'];self.drag=None;self.doc=Document.deserialize(state);self.rebuild();self.update_title()

    def undo(self):
        self.cancel_drag()
        if self.history:
            self.future.append(self.doc.serialize());self.doc=Document.deserialize(self.history.pop());self.rebuild();self.update_title()

    def redo(self):
        self.cancel_drag()
        if self.future:
            self.history.append(self.doc.serialize());self.doc=Document.deserialize(self.future.pop());self.rebuild();self.update_title()

    def may_discard(self):
        self.cancel_drag()
        if self.doc.serialize()==self.saved:return True
        return QMessageBox.question(self,'Unsaved layout','Discard unsaved layout changes? Use Save Copy As to keep them.',QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)==QMessageBox.StandardButton.Discard

    def open_dialog(self):
        if not self.may_discard():return
        path,_=QFileDialog.getOpenFileName(self,'Open Schematic',str(self.path.parent) if self.path else '', 'VerilogCanvas (*.vsch)')
        if path:self.load(path)

    def load(self,path):
        try:document=Document.load(path)
        except Exception as exc:QMessageBox.critical(self,'Open Schematic',str(exc));return False
        self.drag=None;self.doc=document;self.path=Path(path);self.saved=self.doc.serialize();self.history=[];self.future=[]
        self.rebuild();self.fit();self.update_title();return True

    def save_copy(self):
        self.cancel_drag()
        suggested=str(self.path.with_name(self.path.stem+'_qt_layout.vsch')) if self.path else 'qt_layout.vsch'
        path,_=QFileDialog.getSaveFileName(self,'Save Layout Copy',suggested,'VerilogCanvas (*.vsch)')
        if not path:return
        if not path.lower().endswith('.vsch'):path+='.vsch'
        if self.path and Path(path).resolve()==self.path.resolve():
            QMessageBox.information(self,'Save a copy','Choose another filename. This preview saves layout copies, leaving the opened file intact.');return
        try:self.doc.save(path)
        except Exception as exc:QMessageBox.critical(self,'Save Copy',str(exc));return
        self.saved=self.doc.serialize();self.update_title();self.statusBar().showMessage(f'Saved layout copy: {path}',6000)

    def about(self):
        QMessageBox.information(self,'Qt Preview 0.2',
            'Performance preview using the existing schematic model.\n\n'
            'Open .vsch; Ctrl+wheel zoom; wheel scroll; Shift+wheel horizontal scroll; middle-drag pan; Home fit.\n'
            'Drag modules, I/O symbols, comments, groups, wire segments, free ends and labels. Ctrl+drag moves a member independently. '
            'Drag empty space to select an area. Undo/redo and Esc cancellation are available.\n\n'
            'Save Copy As writes a .vsch layout copy usable by the stable editor.\n'
            'Not yet included: creating/deleting objects, property/source editors, resizing, new wire drawing, HDL/PNG export.\n\n'
            'Grid: Dots uses a cached repeating texture; Lines and Off allow comparison. The snap grid remains unchanged.\n\n'
            'Paint time and updates/s describe Qt viewport repaints, not display refresh rate.')

    def closeEvent(self,event):
        if self.may_discard():event.accept()
        else:event.ignore()


def main():
    from qt_editor import EditorWindow
    app=QApplication(sys.argv);app.setStyle('Fusion');window=EditorWindow();window.show()
    if len(sys.argv)>1:QTimer.singleShot(0,lambda:window.load(sys.argv[1]))
    sys.exit(app.exec())

if __name__=='__main__':main()
