"""Draw the manuscript schematics directly as font-embedded vector PDFs.

Run: python figures/draw_schematics.py --output figures
Requires Python 3.9+ and Matplotlib. No TeX engine or network is used.
The diagrams express the defined model; they are not measurement plots.
"""
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon, Circle, FancyArrowPatch

plt.rcParams.update({'font.family':'STIXGeneral', 'mathtext.fontset':'stix',
                     'font.size':9, 'pdf.fonttype':42, 'ps.fonttype':42,
                     'text.usetex':False, 'axes.unicode_minus':False})
CM = 1 / 2.54

class Drawing:
    def __init__(self, bounds):
        x0,y0,x1,y1 = bounds
        self.fig = plt.figure(figsize=((x1-x0)*CM,(y1-y0)*CM))
        self.ax = self.fig.add_axes([0,0,1,1], xlim=(x0,x1), ylim=(y0,y1))
        self.ax.set_aspect('equal'); self.ax.axis('off')
        self.nodes = {}
        self.labels = []

    def text(self,x,y,label,size=9,ha='center',va='center'):
        artist=self.ax.text(x,y,label,fontsize=size,ha=ha,va=va,
                            linespacing=1.15,clip_on=False,zorder=4)
        self.labels.append([artist,None])
        return artist

    def box(self,name,x,y,w,h,label,dashed=False,shape='rect',size=9):
        style = {'edgecolor':'black','facecolor':'white','linewidth':.55,
                 'linestyle':(0,(4,3)) if dashed else 'solid', 'zorder':2}
        if shape == 'diamond':
            obj = Polygon([(x-w/2,y),(x,y+h/2),(x+w/2,y),(x,y-h/2)],**style)
        elif shape == 'circle': obj = Circle((x,y),w/2,**style)
        else: obj = Rectangle((x-w/2,y-h/2),w,h,**style)
        self.ax.add_patch(obj); self.text(x,y,label,size)
        self.labels[-1][1]=(x-w/2,y-h/2,x+w/2,y+h/2)
        self.nodes[name] = (x,y,w,h,shape)

    def point(self,name,side):
        x,y,w,h,_ = self.nodes[name]
        return {'n':(x,y+h/2),'s':(x,y-h/2),'e':(x+w/2,y),
                'w':(x-w/2,y),'nw':(x-w/2,y+h/2),
                'ne':(x+w/2,y+h/2),'c':(x,y)}[side]

    def line(self,points,dashed=False):
        xs,ys=zip(*points)
        self.ax.plot(xs,ys,color='black',linewidth=.55,
                     linestyle=(0,(4,3)) if dashed else 'solid',zorder=1)

    def arrow(self,p,q,dashed=False,via=()):
        points=[p,*via,q]
        if via:self.line(points[:-1],dashed)
        self.ax.add_patch(FancyArrowPatch(points[-2],points[-1],
                         arrowstyle='-|>',mutation_scale=7.5,linewidth=.55,
                         color='black',shrinkA=0,shrinkB=0,
                         linestyle=(0,(4,3)) if dashed else 'solid',zorder=1))

    def edge(self,a,b,sa='s',sb='n',**kwargs):
        self.arrow(self.point(a,sa),self.point(b,sb),**kwargs)

    def frame(self,x,y,w,h):
        self.ax.add_patch(Rectangle((x,y),w,h,fill=False,edgecolor='black',
                                   linewidth=.55,linestyle=(0,(4,3)),zorder=0))

    def save(self,out,name):
        # Fixed physical canvas: do not enlarge or rasterize the scientific figure.
        self.fig.canvas.draw()
        renderer=self.fig.canvas.get_renderer()
        x0,x1=self.ax.get_xlim();y0,y1=self.ax.get_ylim()
        for artist,node in self.labels:
            b=artist.get_window_extent(renderer).transformed(self.ax.transData.inverted())
            if b.x0<x0-.02 or b.x1>x1+.02 or b.y0<y0-.02 or b.y1>y1+.02:
                raise ValueError(name+': clipped label '+repr(artist.get_text()))
            if node and (b.x0<node[0]-.02 or b.x1>node[2]+.02 or b.y0<node[1]-.02 or b.y1>node[3]+.02):
                raise ValueError(name+': label exceeds node '+repr(artist.get_text()))
        self.fig.savefig(out/(name+'.pdf'),format='pdf',
                         metadata={'Creator':'Python Matplotlib','Producer':None,
                                   'CreationDate':None,'ModDate':None})
        plt.close(self.fig)

def draw(out):
    d=Drawing((-4.35,-9.15,4.75,.9))
    def box(name,x,y,w,h,label):
        d.box(name,x,y,w,h,label,size=8.5);d.ax.patches[-1].set_facecolor('#f3f3f3')
    box('input',0,0,7.45,1.25,'Manifest alternatives, current supports,\nand candidate profiles')
    box('synth',0,-1.75,7.45,1.25,'Bounded frontier synthesizer\nsafe nondominated local guard products')
    box('check',-2.4,-3.95,3.2,1.6,'Independent\ncertificate\nchecker')
    box('origin',2.4,-3.95,3.2,1.6,'Durable origin journal\nacquire $\\rightarrow$ commit\n$\\rightarrow$ retire')
    box('owners',0,-6.55,7.45,1.45,'Owner guard stores $1\\ldots n$\ndurable holds, sequence windows,\nand closed floors')
    box('mutate',0,-8.45,7.45,1.25,'Serialized support update\nallowed only if every live local guard remains true')
    d.edge('input','synth')
    d.arrow((-3.725,-2.375),d.point('check','n'),via=[(-3.725,-2.9),(-2.4,-2.9)])
    d.text(-3.55,-2.7,'certificate',size=8.5,ha='left')
    d.edge('check','origin','e','w');d.text(0,-3.3,'validated\nplan',size=8.5)
    d.arrow(d.point('origin','s'),(2.4,-6.55+1.45/2))
    d.text(2.65,-5.3,'prepare /\nclose',size=8.5,ha='left')
    d.arrow(d.point('owners','w'),(.8,-4.75),dashed=True,via=[(-4.15,-6.55),(-4.15,-5.4),(.8,-5.4)])
    d.text(-1.6,-5.2,'receipts',size=8.5)
    d.edge('owners','mutate');d.text(.15,-7.55,'gate',size=8.5,ha='left')
    d.save(out,'architecture')

    d=Drawing((-1.25,-.9,2.55,2.15))
    for i in range(2):
        for j in range(2):
            d.box('cell'+str(i)+str(j),(i+.5)*1.15,(j+.5)*.9,1.15,.9,'$\\checkmark$' if i==j else '$\\times$',size=9)
            if i==j:d.ax.patches[-1].set_facecolor('#e6e6e6')
    d.frame(-.07,-.06,2.44,1.92)
    d.text(.575,-.2,'old',size=9);d.text(1.725,-.2,'new',size=9)
    d.text(-.15,.45,'old',size=9,ha='right');d.text(-.15,1.35,'new',size=9,ha='right')
    d.text(1.15,-.68,'Endpoint 1',size=9)
    artist=d.text(-1.02,.9,'Endpoint 0',size=9);artist.set_rotation(90)
    d.save(out,'relation')

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path(__file__).resolve().parent)
    output=parser.parse_args().output
    output.mkdir(parents=True,exist_ok=True)
    draw(output)
