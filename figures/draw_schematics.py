"""Redraw the planning/authority boundary and the exact compatibility matrix."""
import argparse
from pathlib import Path
from pictograms import icon
from figure_style import AMBER, BLUE, INK, LIGHT, MINT, MUTED, RULE, SAND, TEAL, Plate, paper_style


def draw(out):
    from diagram_ink import emit
    emit('architecture',out)
    relation(out)


def relation(out):
    d=Plate(217,118)
    d.text(127,105,'Endpoint 1',9.6)
    d.text(5,52,'Endpoint 0',9.6,ha='left')
    d.frame(80,22,96,60,'white',MUTED,dash=True)
    for i,x in enumerate((104,152)):
        d.text(x,92,('Old','New')[i],9.6)
    for j,y in enumerate((66,38)):
        d.text(73,y,('Old','New')[j],9.6,ha='right')
        for i,x in enumerate((104,152)):
            if i==j:
                d.frame(x-12,y-9,24,18,MINT,MINT)
                d.dot(x,y,'',fill=TEAL,edge=TEAL,r=3.9)
            else:
                d.rule(x-4,y-4,x+4,y+4,c=AMBER,lw=1.35)
                d.rule(x-4,y+4,x+4,y-4,c=AMBER,lw=1.35)
    d.dot(12,10,'',fill=TEAL,edge=TEAL,r=3.1)
    d.text(20,10,'Allowed',8.7,ha='left')
    d.rule(68,7,74,13,c=AMBER,lw=1.2)
    d.rule(68,13,74,7,c=AMBER,lw=1.2)
    d.text(79,10,'Incompatible',8.7,ha='left')
    d.frame(135,7,13,6,'white',MUTED,dash=True)
    d.text(153,10,'Marginal product',8.7,ha='left')
    d.save(out,'relation')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent)
    paper_style('tpds')
    out=parser.parse_args().output
    draw(out)
    from diagram_ink import emit_supplemental
    emit_supplemental(out)
