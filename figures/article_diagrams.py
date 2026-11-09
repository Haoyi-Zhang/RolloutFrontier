"""Planning authority, durable holds, and retirement order."""
from diagram_ink import Diagram,S,T,A,K,G,F,L,P,O


def architecture():
    d=Diagram(252,153)
    d.tag(8,143,'Planning')
    d.mark('code',35,118,18,S);d.txt(35,100,'Manifest',8.8)
    d.wire((48,118),(88,118),c=S)
    d.mark('graph',103,118,19,S);d.txt(103,100,'Selected product',8.6)
    d.wire((117,118),(162,118),c=S)
    d.mark('cert',175,118,19,S)
    d.txt(190,118,'Verify safety',8.8,ha='left')
    d.tag(8,83,'Runtime')
    d.wire((175,104),(175,77),(144,77),c=S)
    d.mark('store',132,77,18,T);d.txt(119,77,'Origin journal',8.7,ha='right',color=T)
    d.wire((119,67),(48,32),c=T)
    d.wire((145,67),(216,32),c=T)
    d.wire((62,32),(128,64),c=S,dash=True)
    d.wire((202,32),(136,64),c=S,dash=True)
    d.txt(67,55,'Prepare',8.4,color=T)
    d.txt(132,34,'Receipts',8.5,color=S)
    for x,lab in [(54,'Owner A'),(210,'Owner B')]:
        d.mark('lock',x,23,16,T)
        d.txt(x,8,lab+' hold',8.8)
    return d


def guard_lifetime():
    d=Diagram(252,55)
    d.txt(8,42,'Origin',8.4,ha='left',bold=True)
    d.txt(8,15,'Owners',8.4,ha='left',bold=True)
    d.wire((47,42),(239,42),c=S,arrow=False)
    d.wire((47,15),(239,15),c=T,arrow=False)
    for x,y,c,lab in [(77,15,T,'Hold'),(113,42,S,'Commit'),(169,42,A,'Retire'),(205,15,A,'Close')]:
        d.dotmark(x,y,3,c=c,fill='white')
        d.txt(x,25 if y==15 else 50,lab,8.2,color=c)
    d.wire((82,17),(105,38),c=T)
    d.wire((175,38),(197,18),c=A)
    d.txt(139,28,'Use',8.2,color=S)
    return d


FIGURES={f.__name__.replace('_','-'):f for f in (architecture,guard_lifetime)}
