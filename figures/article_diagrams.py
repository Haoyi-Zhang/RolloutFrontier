"""Planning authority, durable holds, and retirement order."""
from diagram_ink import Diagram,S,T,A,K,G,F,L,P,O
from matplotlib.patches import FancyBboxPatch


def architecture():
    d=Diagram(252,170)
    d.tag(9,158,'(a) Safe joint support')
    for x,t in ((78,'B old'),(125,'B new')):
        d.txt(x,140,t,8.9)
    for y,t in ((123,'A old'),(104,'A new')):
        d.txt(39,y,t,8.9)
    for x,y,ok in ((78,123,True),(125,123,False),(78,104,False),(125,104,True)):
        d.mark('check' if ok else 'reject',x,y,11,T if ok else A)
    d.zone(69,115,18,16,c=T,fill='none',dash=False)
    d.txt(176,123,'Old/old selected',9,color=T)
    d.wire((69,120),(58,114),(58,92),(33,92),(33,69),c=S)
    d.tag(83,86,'(b) Durable admission')
    d.mark('doc',33,60,16,S)
    d.txt(33,39,'Prepare',8.6,color=S)
    d.wire((43,60),(68,60),c=S,arrow=False)
    d.dotmark(68,60,1.5,c=S,fill=S)
    for y,name in ((71,'A'),(46,'B')):
        d.wire((70,60),(92,y),c=S)
        d.ax.add_patch(FancyBboxPatch((95,y-7),61,14,boxstyle='round,pad=0,rounding_size=3',
                      linewidth=.73,edgecolor=T,facecolor='white',zorder=3))
        d.mark('store',105,y,10,T)
        d.txt(130,y,rf'Persist {name}',8.1,color=T)
        d.wire((158,y),(176,60),c=T,dash=True,arrow=False)
    d.diamond(182,60,5,T)
    d.wire((188,60),(219,60),c=T)
    d.mark('check',228,60,12,T)
    d.txt(213,72,'All pass',8.5,color=T)
    d.txt(224,46,'Commit',8.7,color=T)
    d.txt(168,33,'Receipts + implication',8.2,ha='right',color=G)
    d.wire((182,54),(182,17),(194,17),c=A,dash=True)
    d.txt(191,34,'Fail',8.5,ha='left',color=A)
    d.txt(223,19,'Retire attempt',8.0,color=A)
    d.txt(223,6,'Schedule closes',7.7,color=A)
    return d


def guard_lifetime():
    d=Diagram(252,97)
    d.txt(8,66,'Use right',8.9,ha='left')
    d.txt(8,31,'Owner guard',8.9,ha='left')
    for y,a,b,c in ((66,104,152,S),(31,79,218,T)):
        d.wire((a+4,y),(b-4,y),c=c,arrow=False,lw=1.25)
        d.dotmark(a,y,3,c=c,fill=c)
        d.dotmark(b,y,3,c=c)
    for x,y,t,c in ((104,83,'Commit',S),(152,83,'Retire',A),
                    (79,15,'Persist',T),(218,15,'Close',T)):
        d.txt(x,y,t,8.9,color=c)
    d.wire((153,60),(153,50),(216,50),(218,37),c=A,dash=True,arrow=False)
    d.txt(205,65,'No use',8.7,color=A)
    d.txt(185,42,'Close pending',8.2,color=A)
    d.wire((171,5),(237,5),c=G,lw=.56)
    return d


FIGURES={f.__name__.replace('_','-'):f for f in (architecture,guard_lifetime)}
