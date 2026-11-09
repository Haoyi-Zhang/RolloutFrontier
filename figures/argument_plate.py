"""Regenerate the paper's mechanism figures."""
import argparse
import json
from pathlib import Path
from article_diagrams import FIGURES
from diagram_ink import emit
from figure_style import paper_style


def draw(spec,out,previews=None):
    name=spec['name']
    if name in FIGURES:
        return emit(name,out,previews)
    raise ValueError(name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--previews',type=Path)
    args=parser.parse_args()
    spec=json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    paper_style(spec['venue'])
    for item in spec['figures']:
        draw(item,args.output,args.previews)


if __name__=='__main__':
    main()
