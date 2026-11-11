"""The two safe boxes in the schedule counterexample."""
from diagram_ink import Diagram, S, T, A, F
from matplotlib.patches import Rectangle

def mass_schedule():
    d=Diagram(248,88)
    xs=(42,68,94)
    for x,b in zip(xs,range(3)):d.txt(x,70,str(b),9.4)
    for y,a in ((48,0),(23,1)):d.txt(16,y,str(a),9.4)
    d.txt(68,82,'Owner B',9.3)
    d.txt(20,82,'Owner A',9.3)
    d.ax.add_patch(Rectangle((30,40),76,16,fill=False,lw=.8,edgecolor=S))
    d.ax.add_patch(Rectangle((35,13),14,48,fill=False,lw=.8,edgecolor=T,ls='--'))
    for x in xs:d.dotmark(x,48,2.45,c=S,fill=S)
    d.dotmark(42,23,2.45,c=T,fill=T)
    d.txt(183,80,r'A proposes $1$ then $0$',9.1)
    d.txt(183,67,r'B stays at $0$',8.7)
    d.wire((116,46),(130,46),c=S,arrow=False)
    d.txt(136,46,'Mass 3: block, no-op',8.8,ha='left',color=S)
    d.wire((116,22),(130,22),c=T,dash=True,arrow=False)
    d.txt(136,22,'Mass 2: install twice',8.8,ha='left',color=T)
    return d

FIGURES={'mass-schedule':mass_schedule}
