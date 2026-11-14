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
    from expansion_diagrams import relation as diagram
    diagram().audited_save(out,'relation')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent)
    paper_style('tpds')
    out=parser.parse_args().output
    draw(out)
    from diagram_ink import emit_supplemental
    emit_supplemental(out)
