"""Exact guard and receipt paths; render with the article figure driver."""
from diagram_ink import Diagram, S, T, A, G, L, O
from matplotlib.textpath import TextPath


def chips(d, x, y, values, active=False):
    ink = S if active else G
    for off, value in zip((-11, 11), values):
        d.block(x+off-10, y-6.4, 20, 12.8, ink, L if active else 'white')
        d.txt(x+off, y, value, 8.4, color=ink)


def architecture():
    """Follow a checked product into acquisition and separate its exit paths."""
    d = Diagram(252, 170)
    def guard_pair(x, y):
        # The same verified guards feed acquisition; they are not a token.
        for off, guard in ((-14, 'A:old'), (14, 'B:old')):
            d.block(x+off-12.5, y-5.5, 25, 11, T, L)
            d.txt(x+off, y, guard, 8.0, color=T, bold=True)

    d.tag(6, 162, '(a) Select a safe product')
    d.txt(35, 145, 'Manifest', 9.4, bold=True)
    chips(d, 34, 126, ('old', 'old'), True)
    chips(d, 34, 108, ('new', 'new'))
    d.txt(23, 136, 'A', 7.8, color=G)
    d.txt(45, 136, 'B', 7.8, color=G)
    d.wire((56, 126), (76, 126), c=S)

    d.txt(107, 145, 'Exact frontier', 9.4, bold=True)
    d.mark('guard', 89, 126, 13, T)
    d.txt(106, 126, 'A', 8.7, color=T)
    d.mark('guard', 124, 126, 13, T)
    d.txt(138, 126, 'B', 8.7, color=T)
    d.mark('cert', 86, 105, 14, S)
    d.txt(96, 105, 'Certificate', 8.3, ha='left')
    d.wire((143, 126), (151, 126), arrow=False, c=S)
    d.wire((140, 105), (151, 105), (151, 126), arrow=False, c=S)
    d.dotmark(151, 126, 1.3, c=S, fill=S)
    d.wire((151, 126), (167, 126), c=S)

    d.txt(199, 148, 'Independent check', 9.3, bold=True)
    d.diamond(175, 126, 7, S)
    d.txt(175, 137, 'Valid?', 8.9)
    d.wire((182, 126), (216, 126), c=A, dash=True)
    d.txt(200, 134, 'No', 8.1, color=A)
    d.mark('reject', 225, 126, 13, A)
    d.txt(225, 114, 'No attempt', 8.5, color=A)
    d.wire((175, 119), (175, 105.3), c=T)
    d.txt(166, 114, 'Yes', 7.8, ha='right', color=T)
    guard_pair(175, 97.5)
    d.txt(206, 97.5, 'Verified', 8.3, ha='left', color=T)

    d.tag(6, 89, '(b) Acquire the verified pair')
    guard_pair(29, 75)
    d.wire((29, 69), (29, 64), c=T)
    d.mark('store', 29, 53, 18, S)
    d.txt(29, 37, 'Acquiring', 9.1, color=S)
    # Await A before requesting B; an absent or non-hold reply ends collection.
    d.txt(77, 66, 'Prepare', 8.45, color=S)
    d.wire((40, 51), (54, 51), c=S)
    for x, who in ((64, 'A'), (101, 'B')):
        d.mark('cert', x, 51, 16, T)
        d.txt(x, 37, who, 8.9, color=T, bold=True)
    d.wire((73, 51), (91, 51), c=T)
    d.txt(82, 57, 'Receipt', 7.6, color=T)
    d.wire((110, 51), (119, 51), c=T)
    # Both prepare failures share the same retirement exit as check failure.
    d.wire((64, 31), (64, 25), (126, 25), c=A, dash=True, arrow=False)
    d.wire((101, 31), (101, 25), c=A, dash=True, arrow=False)
    d.dotmark(126, 25, 1.25, c=A, fill=A)
    d.txt(85, 17, 'Missing or not held', 8.0, color=A)
    for x,head,subject,predicate in ((126,122,'Receipts','Bound?'),(159,163,'Manifest','Implied?')):
        d.diamond(x,51,6,S)
        d.txt(head,76,subject,8.3,bold=True)
        d.txt(head,65,predicate,8.25)
        d.wire((x,44),(x,12),c=A,dash=True,arrow=False)
    d.wire((133,51),(152,51),c=T)
    d.wire((166,51),(186,51),c=T)
    d.diamond(193,51,6,S)
    d.txt(204,76,'Acquiring',8.3,bold=True)
    d.txt(199,65,'state?',8.25)
    d.wire((200,51),(206,51),c=T)
    d.mark('check',212,51,11,T)
    d.txt(220,51,'Commit',8.6,ha='left',color=T,bold=True)
    d.wire((193,44),(193,32),(205,32),c=A,dash=True,arrow=False)
    d.wire((205,29.5),(205,34.5),c=A,arrow=False)
    d.txt(201,39,'No',7.8,color=A)
    d.txt(211,32,'No commit',8.1,ha='left',color=A)
    d.wire((126,12),(201,12),c=A,dash=True)
    d.dotmark(159,12,1.25,c=A,fill=A)
    d.txt(137,38,'No',7.8,color=A)
    d.txt(171,38,'No',7.8,color=A)
    d.mark('store',209,12,13,A)
    d.txt(219, 17, 'Retire', 8.9, ha='left', color=A, bold=True)
    d.txt(215,5.2,'Send closes',7.4,ha='left',color=A)
    return d


def guard_lifetime():
    """Snapshots immediately after each event for one successful admission."""
    d = Diagram(252, 97)
    stages = (
        (78, 'Prepare', 'Not yet', False, 'Held', True),
        (122, 'Commit', 'Authorized', True, 'Held', True),
        (166, 'Retire', 'Revoked', False, 'Still held', True),
        (221, 'Durable close', 'Revoked', False, 'Released', False),
    )
    d.band(145, 3, 42, 90, O)
    d.mark('keyed', 10, 51, 13, S)
    d.txt(20, 51, 'Use right', 8.8, ha='left')
    d.mark('guard', 10, 26, 13, T)
    d.txt(20, 26, 'Guard', 8.8, ha='left')
    for index, (x, event, right, usable, guard, held) in enumerate(stages, 1):
        d.dotmark(x, 84, 6.5, c=A if index == 3 else G)
        token=d.txt(x,84,str(index),8.0,bold=True,color=A if index==3 else G)
        ink_box=TextPath((0,0),str(index),prop=token.get_fontproperties()).get_extents()
        token.set(ha='left',va='baseline',
                  position=(x-(ink_box.x0+ink_box.x1)/2,84-(ink_box.y0+ink_box.y1)/2))
        d.txt(x, 68, event, 9.0, bold=True)
        for y, label, active, ink in ((51, right, usable, S), (28, guard, held, T)):
            color = ink if active else G
            d.dotmark(x, y, 2.6, c=color, fill=color if active else 'white')
            d.txt(x, y-9, label, 8.6, bold=(index == 3), color=color)
    d.txt(166, 7, 'Close pending', 8.1, color=A)
    return d


FIGURES = {'architecture': architecture, 'guard-lifetime': guard_lifetime}
