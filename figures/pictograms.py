"""Place cropped regions of the reviewed, text-free illustration plate."""
from functools import lru_cache
from pathlib import Path

from matplotlib import image
import numpy as np

ASSET=Path(__file__).with_name('pictogram-atlas.png')


@lru_cache(maxsize=4)
def glyph(index):
    src=image.imread(ASSET)[...,:3]
    h,w=src.shape[:2]
    r,c=divmod(index,2)
    cut=src[r*h//2:(r+1)*h//2,c*w//2:(c+1)*w//2]
    yy,xx=np.where(cut.min(axis=2)<.82)
    assert len(xx)>2000,index
    border=6
    return cut[max(0,yy.min()-border):yy.max()+border+1,
               max(0,xx.min()-border):xx.max()+border+1]


def icon(d,index,x,y,span=28):
    """Reserve a square in layout points; do not upscale the source pixels."""
    im=glyph(index)
    h,w=im.shape[:2]
    scale=span/max(h,w)
    assert 72/scale>=680,(index,h,w,span)
    w,h=w*scale,h*scale
    limits=d.ax.get_xlim(),d.ax.get_ylim()
    d.ax.imshow(im,extent=(x-w/2,x+w/2,y-h/2,y+h/2),
                interpolation='none',aspect='auto',zorder=2.5)
    d.ax.set_xlim(limits[0]); d.ax.set_ylim(limits[1])
