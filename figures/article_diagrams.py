"""Planning authority, durable holds, and retirement order."""
from diagram_ink import Diagram,S,T,A,K,G,F,L,P,O


def architecture():
    d=Diagram(252,153)
    d.mark('doc',24,123,19,S)
    d.txt(24,142,'Manifest',9.1)
    d.wire((36,123),(74,123),c=S)
    for x,y in [(80,117),(80,125),(89,117),(89,125)]:
        d.block(x,y,7,5,S,'white')
    d.txt(88,142,'Product',9.1)
    d.wire((101,123),(136,123),c=S)
    d.mark('guard',149,123,20,S)
    d.txt(149,142,'Check',9.1)
    d.wire((149,110),(149,97),(37,97),(37,79),c=S)
    d.mark('store',37,67,20,S)
    d.txt(37,49,'Journal',9.1)
    d.wire((50,67),(72,67),c=T,arrow=False)
    d.dotmark(72,67,1.7,c=T,fill=T)
    for y,lab in ((73,'A'),(31,'B')):
        d.wire((74,67),(92,y),(109,y),c=T)
        d.mark('lock',119,y,17,T)
        d.txt(119,y-15,lab,9.5)
        d.wire((130,y),(151,y),(172,67),c=S,dash=True,arrow=False)
    d.dotmark(172,67,1.8,c=S,fill=S)
    d.wire((176,67),(204,67),c=S)
    d.mark('cert',216,67,21,T)
    d.txt(216,48,'Commit',9.5)
    d.txt(207,84,'All receipts',9.1,color=S)
    d.wire((9,13),(23,13),c=T)
    d.txt(28,13,'Prepare',8.8,ha='left',color=T)
    d.wire((166,13),(180,13),c=S,dash=True)
    d.txt(185,13,'Receipt',8.8,ha='left',color=S)
    return d


def guard_lifetime():
    d=Diagram(252,55)
    d.txt(8,40,'Origin',9.1,ha='left')
    d.txt(8,17,'Owners',9.1,ha='left')
    d.wire((48,40),(237,40),c=S)
    d.wire((48,17),(237,17),c=G)
    for x,y,c,lab in [(67,17,T,'Hold'),(105,40,S,'Commit'),(171,40,A,'Retire'),(210,17,A,'Close')]:
        d.dotmark(x,y,3.3,c=c)
        d.txt(x,7 if y==17 else 49,lab,9.0,color=c)
    d.wire((72,20),(99,36),c=T)
    d.wire((176,37),(205,20),c=A)
    d.wire((109,40),(167,40),c=S,arrow=False,lw=1.9)
    d.wire((72,17),(205,17),c=T,arrow=False,lw=1.9)
    d.txt(138,49,'Use',8.9,color=S)
    d.txt(138,28,'Live guard',8.9,color=T)
    return d


FIGURES={f.__name__.replace('_','-'):f for f in (architecture,guard_lifetime)}
