from scripts.image_puzzle import locate_gap


def test_dark_gap_matches_piece_silhouette():
    w,h=160,60
    bg=[220,220,220,255]*(w*h);piece=[0,0,0,0]*(w*h)
    shape={(x,y) for x in range(8,28) for y in range(15,35)}|{(x,y) for x in range(15,21) for y in range(10,15)}
    for x,y in shape:
        piece[(y*w+x)*4:(y*w+x)*4+4]=[150,150,150,255]
        bg[(y*w+x+80)*4:(y*w+x+80)*4+4]=[40,40,40,255]
    assert locate_gap(w,h,bg,piece)['shift']==80
    assert locate_gap(w,h,[220,220,220,255]*(w*h),piece) is None


def test_rejects_unsupported_images():
    assert locate_gap(1000,60,[],[]) is None
    assert locate_gap(160,60,[0]*38400,[0]*38400) is None
