"""Redraw the planning/authority boundary and the exact compatibility matrix."""
import argparse
from pathlib import Path
from pictograms import icon
from figure_style import AMBER, BLUE, INK, LIGHT, MINT, MUTED, RULE, SAND, TEAL, Plate, paper_style


def draw(out):
    from diagram_ink import emit
    emit('architecture',out)

    d=Plate(217,118)
    d.text(123,105,'Endpoint 1',10.3,weight='bold')
    d.text(8,54,'Endpoint 0',10.1,ha='left',weight='bold')
    d.frame(84,22,78,60,'white',RULE,dash=True)
    for i,x in enumerate((104,142)):
        d.text(x,92,('Old','New')[i],9.6)
    for j,y in enumerate((66,38)):
        d.text(77,y,('Old','New')[j],9.6,ha='right')
        for i,x in enumerate((104,142)):
            if i==j:
                d.dot(x,y,'',fill=TEAL,edge=TEAL,r=4.3)
            else:
                d.rule(x-4,y-4,x+4,y+4,c=AMBER,lw=1.35)
                d.rule(x-4,y+4,x+4,y-4,c=AMBER,lw=1.35)
    d.dot(66,10,'',fill=TEAL,edge=TEAL,r=3.3)
    d.text(74,10,'Allowed',9.2,ha='left')
    d.rule(133,7,139,13,c=AMBER,lw=1.25)
    d.rule(133,13,139,7,c=AMBER,lw=1.25)
    d.text(144,10,'Unsafe',9.2,ha='left')
    d.save(out,'relation')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent)
    paper_style('tpds')
    out=parser.parse_args().output
    draw(out)
    from diagram_ink import emit_supplemental
    emit_supplemental(out)
