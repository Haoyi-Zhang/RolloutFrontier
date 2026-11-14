"""The two safe boxes in the schedule counterexample."""
from diagram_ink import Diagram, S, T, A, F, G
from matplotlib.patches import Rectangle

def relation():
    d=Diagram(248,111)
    d.txt(143,99,'Endpoint B',9.4,bold=True)
    d.txt(11,63,'Endpoint A',9.4,ha='left',bold=True)
    for x,label in ((115,'Old'),(170,'New')):
        d.txt(x,84,label,9.2)
    for y,label in ((63,'Old'),(39,'New')):
        d.txt(87,y,label,9.2,ha='right')
    for row,y in enumerate((63,39)):
        for col,x in enumerate((115,170)):
            same=row==col
            d.block(x-23,y-10,46,20,T if same else F,'white')
            d.mark('check' if same else 'reject',x,y,11,T if same else A)
    d.mark('check',52,16,10,T)
    d.txt(63,16,'Allowed',9.0,ha='left',color=T)
    d.mark('reject',130,16,10,A)
    d.txt(141,16,'Incompatible',9.0,ha='left',color=A)
    return d

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
    d.txt(170,82,r'A proposes $1$ then $0$',9.0,bold=True)
    for x,t in ((113,'Mass'),(138,'Start'),(173,'After 1'),(207,'After 0')):
        d.txt(x,64,t,8.3,color=G)
    for y,c,mass,states,outcomes in ((46,S,'3',(0,0,0),('Blocked','No-op')),
                                    (22,T,'2',(0,1,0),('Install','Install'))):
        d.txt(113,y,mass,8.4,color=c,bold=True)
        for x,state in zip((138,173,207),states):
            d.dotmark(x,y,5,c=c)
            d.txt(x,y,str(state),7.6,color=c)
        for (x1,x2),outcome in zip(((145,166),(180,200)),outcomes):
            d.wire((x1,y),(x2,y),c=c,dash=mass=='3',lw=.67)
            d.txt((x1+x2)/2,y-9,outcome,6.8,color=c)
    d.txt(65,5,r'B stays at $0$',8.2,color=G)
    return d

FIGURES={'mass-schedule':mass_schedule,'relation':relation}
