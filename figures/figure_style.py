"""Publication artwork primitives. Python + Matplotlib; no TeX renderer."""
import argparse
from pathlib import Path
import os
import shutil
import subprocess

import matplotlib as mpl
mpl.use("Agg")
from matplotlib import pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, Rectangle, Circle, FancyBboxPatch

INK = "#15202c"
MUTED = "#485461"
BLUE = "#265776"
TEAL = "#176a61"
AMBER = "#9b481e"
PURPLE = "#634c83"
LIGHT = "#eff4f7"
MINT = "#ecf5f2"
SAND = "#fcf1e9"
RULE = "#cad1d6"
WHITE = "#ffffff"
SERIES = [(BLUE, "o", "-"), (AMBER, "s", "--"), (TEAL, "^", "-.")]


def _figure_font(filename, font_dir):
    directory = font_dir or os.environ.get("FIGURE_TEX_FONT_DIR")
    if directory and (p := Path(directory) / filename).is_file():
        return p
    if kpse := shutil.which("kpsewhich"):
        r = subprocess.run([kpse, filename], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and (p := Path(r.stdout.strip())).is_file():
            return p
    raise RuntimeError(f"Missing {filename}; use the paper's TeX fonts (FIGURE_TEX_FONT_DIR or kpsewhich).")


def paper_style(venue="tosem", font_dir=None):
    # Load the actual manuscript faces, not a metrically similar substitute.
    # Matplotlib embeds these CFF/Type 1 faces as vector Type 3 subsets.
    tpds = venue == "tpds"
    family = "Nimbus Roman No9 L" if tpds else "Linux Libertine O"
    faces = (("utmr8a.pfb", "utmb8a.pfb", "utmri8a.pfb", "utmbi8a.pfb") if tpds else
             ("LinLibertine_R.otf", "LinLibertine_RB.otf", "LinLibertine_RI.otf", "LinLibertine_RBI.otf"))
    prefix = "NimbusRomNo9L-" if tpds else "LinLibertineO"
    for filename, (weight, style) in zip(faces, ((400,"normal"),(700,"normal"),(400,"italic"),(700,"italic"))):
        path = str(_figure_font(filename, font_dir).resolve())
        font = font_manager.get_font(path)
        if font.family_name != family or not font.postscript_name.startswith(prefix):
            raise RuntimeError(f"{filename} is {font.postscript_name}; expected the manuscript family {family}.")
        if not any(e.fname == path for e in font_manager.fontManager.ttflist):
            # Type 1 files lack an SFNT name table; the checked face information
            # above makes registration possible without converting the outlines.
            font_manager.fontManager.ttflist.insert(
                0,font_manager.FontEntry(fname=path,name=family,style=style,weight=weight,
                                         stretch="normal",size="scalable"))
    mpl.rcParams.update({
        "font.family": family, "font.size": 9, "mathtext.fontset": "cm" if tpds else "custom",
        "mathtext.rm": family, "mathtext.it": family+":italic",
        "mathtext.bf": family+":bold", "mathtext.fallback": "stix",
        "axes.linewidth": .7, "axes.labelpad": 3.5, "xtick.major.pad": 2.5,
        "ytick.major.pad": 2.5, "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
        "lines.linewidth": .72, "lines.markersize": 3.5,
        "pdf.fonttype": 3, "svg.fonttype": "none", "text.usetex": False,
        "axes.unicode_minus": False, "axes.spines.right": False,
        "axes.spines.top": False, "axes.edgecolor": MUTED,
        "axes.labelcolor": INK, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "xtick.major.size": 3, "ytick.major.size": 3,
        "axes.titlesize": 9.6, "legend.frameon": False, "legend.fontsize": 8.5,
        "savefig.facecolor": WHITE, "figure.facecolor": WHITE,
    })
    return family


def save(fig, out, name, previews=None):
    out.mkdir(parents=True, exist_ok=True)
    fig.canvas.draw()
    render = fig.canvas.get_renderer()
    for a in fig.axes:
        for t in a.texts:
            if not t.get_visible(): continue
            b = t.get_window_extent(render)
            extent = fig.bbox
            if b.x0 < extent.x0 - 1 or b.y0 < extent.y0 - 1 or b.x1 > extent.x1 + 1 or b.y1 > extent.y1 + 1:
                raise ValueError(f"{name}: cropped label {t.get_text()}")
    fig.savefig(out/(name+".pdf"), metadata={"Creator":"Python Matplotlib",
                "Producer":None, "CreationDate":None, "ModDate":None})
    if previews:
        previews.mkdir(parents=True,exist_ok=True)
        fig.savefig(previews/(name+".svg"), metadata={"Date":None})
        fig.savefig(previews/(name+".png"), dpi=600)
    plt.close(fig)
    print("[fig] saved", name, flush=True)


def plot(width, height, left=55, right=9, bottom=29, top=15):
    f = plt.figure(figsize=(width/72,height/72))
    ax = f.add_axes([left/width,bottom/height,1-(left+right)/width,1-(bottom+top)/height])
    return f, ax


def grid(a, axis="y"):
    a.grid(axis=axis, color=RULE, linewidth=.45, alpha=.65)
    a.set_axisbelow(True)


class Plate:
    """Diagram in PDF-point coordinates with native text and routed arrows."""
    def __init__(self, w, h):
        self.fig = plt.figure(figsize=(w/72,h/72))
        self.ax = self.fig.add_axes([0,0,1,1],xlim=(0,w),ylim=(0,h))
        self.ax.set_axis_off()
    def text(self,x,y,t,size=8.5,ha="center",color=INK,weight="normal",**kw):
        return self.ax.text(x,y,t,ha=ha,va="center",fontsize=size,
                            color=color,fontweight=weight,linespacing=1.17,zorder=5,**kw)
    def head(self,x,y,t):
        self.text(x,y,t,9.4,ha="left",weight="bold")
    def rule(self,x1,y1,x2,y2,c=RULE,ls="-",lw=.65):
        self.ax.plot([x1,x2],[y1,y2],color=c,linestyle=ls,lw=lw,zorder=1)
    def frame(self,x,y,w,h,fill=WHITE,edge=RULE,dash=False):
        self.ax.add_patch(Rectangle((x,y),w,h,facecolor=fill,edgecolor=edge,
                                   linestyle="--" if dash else "-",linewidth=.75,zorder=0))
    def band(self,x,y,w,h,fill=LIGHT):
        self.ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0,rounding_size=3",
                          facecolor=fill,edgecolor="none",zorder=0))
    def token(self,x,y,w,h,title,color=BLUE,fill=WHITE,size=9):
        self.ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0,rounding_size=2",
                          facecolor=fill,edgecolor=color,linewidth=.75,zorder=3))
        self.text(x+w/2,y+h/2,title,size,color=color)
    def box(self,x,y,w,h,title,detail=None,tone=BLUE,fill=LIGHT,size=8.5):
        self.frame(x,y,w,h,fill,tone)
        if detail:
            self.text(x+w/2,y+h*.69,title,size,weight="bold")
            self.text(x+w/2,y+h*.33,detail,size)
        else:
            self.text(x+w/2,y+h/2,title,size)
    def dot(self,x,y,t,fill=WHITE,edge=BLUE,r=8):
        self.ax.add_patch(Circle((x,y),r,facecolor=fill,edgecolor=edge,linewidth=.95,zorder=3))
        self.text(x,y,t,8.5)
    def arrow(self,*pts,color=MUTED,dash=False):
        ls="--" if dash else "-"
        for a,b in zip(pts[:-2],pts[1:-1]):
            self.rule(*a,*b,c=color,ls=ls,lw=.9)
        self.ax.add_patch(FancyArrowPatch(pts[-2],pts[-1],arrowstyle="-|>",
                            shrinkA=0,shrinkB=0,mutation_scale=7.2,
                            color=color,lw=.9,linestyle=ls,zorder=2))
    def save(self,out,name,previews=None):
        save(self.fig,out,name,previews)


def arguments():
    p=argparse.ArgumentParser(description="Generate current Python vector artwork from retained inputs.")
    p.add_argument("--outdir",type=Path,default=Path(__file__).resolve().parent)
    p.add_argument("--previews",type=Path,help="Optional editable SVG and 600-dpi PNG directory")
    return p.parse_args()
