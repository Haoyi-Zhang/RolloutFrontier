"""Planning authority, durable holds, and retirement order."""
from diagram_ink import Diagram,S,T,A,K,G,F,L,P,O


def architecture():
    d=Diagram(252,153)
    d.tag(8,143,'Planning')
    d.txt(27,118,'Manifest',9.2,color=S)
    d.wire((50,118),(67,118),c=S)
    d.txt(105,118,'Selected product',9.2,color=S)
    d.wire((144,118),(161,118),c=S)
    d.diamond(170,118,5.3,S)
    d.txt(184,118,'Verify safety',9.1,ha='left')
    d.tag(8,83,'Runtime')
    d.wire((170,111),(170,77),(144,77),c=S)
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
    d.txt(8,39,'Origin',9.0,ha='left',bold=True)
    d.txt(8,15,'Owners',9.0,ha='left',bold=True)
    d.wire((47,39),(239,39),c=S,arrow=False)
    d.wire((47,15),(239,15),c=T,arrow=False)
    for x,y,c,lab in [(77,15,T,'Hold'),(113,39,S,'Commit'),(169,39,A,'Retire'),(205,15,A,'Close')]:
        d.dotmark(x,y,3,c=c,fill='white')
        d.txt(x,25 if y==15 else 48,lab,9.0,color=c)
    d.wire((82,17),(105,35),c=T)
    d.wire((175,35),(197,18),c=A)
    d.txt(139,26,'Use',9.0,color=S)
    return d


FIGURES={f.__name__.replace('_','-'):f for f in (architecture,guard_lifetime)}
