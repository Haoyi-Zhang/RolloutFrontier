"""Compatibility projection and a two-proposal execution trace."""
from diagram_ink import Diagram, S, T, A, F, G, P, O, L


def relation():
    # Enumerating the two whole alternatives gives a diagonal relation.
    # Their Cartesian projection also contains both off-diagonal pairs.
    d = Diagram(248, 111)
    d.mark('array', 75, 99, 16, S)
    d.txt(88, 99, 'B projection', 9.5, ha='left', bold=True)
    for x, token in ((91,'old'),(134,'new')):
        d.txt(x, 82, token, 9.7, color=S)
    d.wire((91,89),(91,92),(134,92),(134,89),c=F,arrow=False,lw=.7)
    d.mark('array', 17, 77, 15, S)
    d.txt(6, 65, 'A projection', 8.7, ha='left', bold=True)
    for i,(y, token) in enumerate(((54,'old'),(29,'new'))):
        d.txt(64, y, token, 9.7, ha='right',color=S)
        for j,x in enumerate((91,134)):
            valid = i == j
            d.block(x-19,y-11,38,22,F,P if valid else O)
            if valid:
                d.mark('check',x-11.5,y,13,T)
                d.txt(x+7,y,rf'$j={1+i}$',8.3,color=T)
            else:
                d.mark('reject',x,y,16,A)
    d.txt(165, 82, 'Whole placement', 9.6, ha='left', bold=True)
    for y,mark,color,label in ((62,'check',T,'Shared branch'),
                               (37,'reject',A,'Incompatible mix')):
        d.mark(mark,174,y,14,color)
        d.txt(185,y,label,8.6,ha='left',color=color)
    d.txt(112, 8, 'Each projection accepts both profiles', 9.1, color=G)
    return d


def mass_schedule():
    d=Diagram(252,89.088)
    d.txt(44,80,'Guard product',9.7,bold=True)
    d.txt(117,80,r'Propose $A := 1$',8.8)
    d.txt(185,80,r'Then $A := 0$',8.8)
    d.txt(233,80,'Installs',8.3,bold=True)
    # Separate the tall math products from their mass labels.  The 30-point
    # row pitch preserves clearance between both two-line groups without
    # changing the type sizes or the column-width canvas.
    for y,product,mass,states,events,ink,tint in (
        (58,r'\{0\}\times\{0,1,2\}',3,(0,0,0),('reject','noop'),S,L),
        (28,r'\{0,1\}\times\{0\}',2,(0,1,0),('check','check'),T,P),
    ):
        d.txt(44,y+6,f'${product}$',10.0,color=ink)
        d.txt(44,y-9,f'Mass {mass}',8.5,color=ink)
        for x,before,after,event in zip((117,185),states,states[1:],events):
            d.block(x-29,y-8.5,58,17,F,tint)
            symbol(d,event,x-20,y,12.5)
            d.txt(x+6,y,rf'${before}\to{after}$',10.05,color=ink)
        d.block(224,y-7.5,18,15,F,'white')
        d.txt(233,y,str(events.count('check')),10.6,color=ink,bold=True)
    for x,event,label in ((14,'reject','Blocked'),(76,'noop','No-op'),(128,'check','Installed')):
        symbol(d,event,x,8,11.5)
        d.txt(x+8,8,label,8.2,ha='left')
    d.txt(242,8,r'$B=0$ throughout',8.2,ha='right',color=G)
    return d


def symbol(d, kind, x, y, size):
    if kind == 'noop':
        d.dotmark(x,y,.28*size,c=G)
        d.ax.plot((x-.15*size,x+.15*size),(y,y),color=G,lw=.78,zorder=5)
    else:
        d.mark(kind,x,y,size,A if kind=='reject' else T)


FIGURES={'mass-schedule':mass_schedule,'relation':relation}
