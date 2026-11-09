"""The two safe boxes in the schedule counterexample."""
from diagram_ink import Diagram, S, T, A, F
from matplotlib.patches import Rectangle

def mass_schedule():
    d=Diagram(248,88)
    xs=(41,69,97)
    for x,b in zip(xs,range(3)):d.txt(x,70,str(b),9.6)
    for y,a in ((48,0),(23,1)):d.txt(15,y,str(a),9.6)
    d.txt(70,82,'Owner B',9.5,bold=True)
    d.txt(15,80,'A',9.5,bold=True)
    d.ax.add_patch(Rectangle((28,38),83,20,fill=False,lw=.95,edgecolor=S))
    d.ax.add_patch(Rectangle((32,12),17,50,fill=False,lw=.95,edgecolor=T,ls='--'))
    for b,x in enumerate(xs):
        for a,y in ((0,48),(1,23)):
            if a==0 or b==0:d.dotmark(x,y,2.6,c=S,fill=S)
    d.txt(183,78,'A toggles; B stays at 0',9.2,bold=True)
    d.wire((130,53),(149,53),c=S,arrow=False)
    d.txt(158,53,'Mass 3: 0 changes',9.0,ha='left',color=S)
    d.wire((130,25),(149,25),c=T,dash=True,arrow=False)
    d.txt(158,25,r'Mass 2: $2T$ changes',9.0,ha='left',color=T)
    return d

FIGURES={'mass-schedule':mass_schedule}
