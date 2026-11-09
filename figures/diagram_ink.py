"""Small vector primitives for the paper's domain-specific diagrams."""
from math import cos, pi, sin
from matplotlib.patches import Circle, Polygon, Rectangle, FancyArrowPatch
from figure_style import Plate, BLUE, TEAL, AMBER, INK, MUTED, RULE, LIGHT, MINT, SAND

S = BLUE
T = TEAL
A = AMBER
K = INK
G = MUTED
F = RULE
L = LIGHT
P = MINT
O = SAND


def crosses_box(a,b,box):
    """Segment against the open interior of an axis-aligned rectangle."""
    low,high=0.,1.
    for i,(lo,hi) in enumerate(((box.x0,box.x1),(box.y0,box.y1))):
        d=b[i]-a[i]
        if not d:
            if a[i]<=lo or a[i]>=hi:return False
            continue
        u,v=sorted(((lo-a[i])/d,(hi-a[i])/d))
        low,high=max(low,u),min(high,v)
        if low>=high:return False
    return True


class Diagram(Plate):
    def __init__(self,w,h):
        super().__init__(w,h)
        self.words=[]
        self.wires=[]

    def txt(self,x,y,label,sz=9.3,*,ha='center',color=K,bold=False):
        t=self.text(x,y,label,sz,ha=ha,color=color,weight='bold' if bold else 'normal')
        self.words.append(t)
        return t

    def tag(self,x,y,label):
        return self.txt(x,y,label,10,ha='left',bold=True)

    def wire(self,*pts,c=G,dash=False,arrow=True,lw=.82):
        self.wires.extend(zip(pts,pts[1:]))
        for a,b in zip(pts,pts[1:]):
            if arrow and b==pts[-1]:
                self.ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',shrinkA=0,shrinkB=0,
                    linewidth=lw,mutation_scale=6.8,linestyle='--' if dash else '-',color=c,zorder=2))
            else:self.rule(*a,*b,c=c,lw=lw,ls='--' if dash else '-')

    def dotmark(self,x,y,r=3,*,c=S,fill='white'):
        self.ax.add_patch(Circle((x,y),r,facecolor=fill,edgecolor=c,linewidth=.9,zorder=4))

    def diamond(self,x,y,r=6,c=S):
        self.ax.add_patch(Polygon([(x-r,y),(x,y+r),(x+r,y),(x,y-r)],closed=True,
                                 facecolor='white',edgecolor=c,lw=.95,zorder=4))

    def zone(self,x,y,w,h,*,c=F,fill='white',dash=True):
        self.frame(x,y,w,h,fill,c,dash)

    def block(self,x,y,w,h,c=S,fill=L):
        self.ax.add_patch(Rectangle((x,y),w,h,edgecolor=c,facecolor=fill,lw=.85,zorder=3))

    def mark(self,kind,x,y,size=21,c=S):
        """Glyphs for actual data objects and observable state, not task cards."""
        def path(*points,fill=None):
            poly=[(x+size*u,y+size*v) for u,v in points]
            if fill:
                self.ax.add_patch(Polygon(poly,closed=True,edgecolor=c,facecolor=fill,lw=.9,
                    joinstyle='round',zorder=3))
            else:
                xx,yy=zip(*poly)
                self.ax.plot(xx,yy,color=c,linewidth=.9,solid_capstyle='round',solid_joinstyle='round',zorder=4)
        def circ(u,v,r=.105,solid=False):
            self.dotmark(x+size*u,y+size*v,r*size,c=c,fill=c if solid else 'white')
        if kind in {'doc','code','cert','trace','keyed','vector','patch'}:
            path((-.34,-.43),(.34,-.43),(.34,.23),(.12,.43),(-.34,.43),fill='white')
            path((.12,.43),(.12,.23),(.34,.23))
            if kind=='code':
                path((-.07,.14),(-.22,0),(-.07,-.14));path((.09,.14),(.24,0),(.09,-.14))
            elif kind=='cert':
                circ(0,0,.15);path((-.13,-.07),(-.18,-.29),(0,-.21),(.18,-.29),(.13,-.07))
            elif kind=='trace':
                path((-.24,-.20),(-.12,-.20),(-.12,.12),(.05,.12),(.05,-.05),(.22,-.05))
            elif kind=='patch':
                path((-.18,0),(.18,0));path((0,-.18),(0,.18))
            elif kind=='vector':
                path((-.24,.10),(.23,.10),(.23,-.16),(-.24,-.16),(-.24,.10))
                for i in (-.08,.08):path((i,-.16),(i,.10))
            else:
                for i in (.13,-.03,-.19):
                    path((-.20,i),(.21,i))
                    if kind=='keyed':circ(-.24,i,.025,True)
        elif kind in {'store','epoch','floor','replica','array'}:
            for i in (-1,0,1):
                yy=i*.23
                path((-.39,yy-.10),(.39,yy-.10),(.39,yy+.10),(-.39,yy+.10),fill='white')
                if kind=='replica':circ(-.28,yy,.035,True)
                if kind=='epoch' and i==0:path((-.22,yy),(.25,yy))
                if kind=='array':
                    for u in (-.13,.13):path((u,yy-.10),(u,yy+.10))
            if kind=='floor':path((-.45,-.36),(.45,-.36))
        elif kind in {'join','branch','graph'}:
            points=[(-.31,.22),(-.31,-.22),(.31,0)]
            if kind=='branch':points=[(.31,.22),(.31,-.22),(-.31,0)]
            path(points[0],points[2]);path(points[1],points[2])
            if kind=='graph':path(points[0],points[1])
            for u,v in points:circ(u,v)
        elif kind in {'guard','reject','check'}:
            if kind=='guard':
                path((-.31,.27),(0,.42),(.31,.27),(.26,-.18),(0,-.41),(-.26,-.18),fill='white')
            else:circ(0,0,.33)
            if kind=='reject':
                path((-.13,.13),(.13,-.13));path((-.13,-.13),(.13,.13))
            else:path((-.15,0),(-.04,-.12),(.18,.15))
        elif kind=='lens':
            circ(-.10,.09,.24);path((.07,-.08),(.34,-.35))
        elif kind=='pin':
            path((-.23,.30),(.23,.30),(.12,.08),(.23,-.09),(-.23,-.09),(-.12,.08),(-.23,.30))
            path((0,-.09),(0,-.38))
        elif kind=='symbol':
            path((-.18,.32),(-.31,.18),(-.31,.06),(-.38,0),(-.31,-.06),(-.31,-.18),(-.18,-.32))
            path((.18,.32),(.31,.18),(.31,.06),(.38,0),(.31,-.06),(.31,-.18),(.18,-.32))
            for u in (-.14,0,.14):circ(u,0,.033,True)
        elif kind=='lock':
            path((-.26,-.34),(.26,-.34),(.26,.10),(-.26,.10),fill='white')
            path((-.17,.10),(-.17,.25),(-.08,.36),(.08,.36),(.17,.25),(.17,.10))
            circ(0,-.12,.047,True)
        elif kind=='clock':
            circ(0,0,.34);path((0,.20),(0,0),(.16,-.09))
        else:raise ValueError(kind)

    def audited_save(self,out,name,previews=None):
        self.fig.canvas.draw()
        renderer=self.fig.canvas.get_renderer()
        inv=self.ax.transData.inverted()
        groups=[]
        for w in self.words:
            bb=w.get_window_extent(renderer).transformed(inv)
            assert bb.x0>=-.05 and bb.y0>=-.05 and bb.x1<=self.ax.get_xlim()[1]+.05 and bb.y1<=self.ax.get_ylim()[1]+.05,(name,w.get_text(),bb.extents)
            for old,other in groups:
                assert not bb.shrunk(.97,.92).overlaps(old.shrunk(.97,.92)),(name,w.get_text(),other)
            for a,b in self.wires:
                assert not crosses_box(a,b,bb.shrunk(.92,.82)),(name,w.get_text(),a,b)
            groups.append((bb,w.get_text()))
        self.save(out,name,previews)


def emit(name,out,previews=None):
    from article_diagrams import FIGURES
    FIGURES[name]().audited_save(out,name,previews)


def emit_supplemental(out,previews=None):
    import json
    from pathlib import Path
    from argument_plate import draw
    path=Path(__file__).with_name('argument_plate.json')
    for item in json.loads(path.read_text(encoding='utf-8'))['figures']:
        draw(item,out,previews)
