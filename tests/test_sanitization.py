from pathlib import Path

def test_no_removed_organization_specific_content():
    root=Path(__file__).parents[1]
    # Build the prohibited strings without spelling them in package content.
    banned=["tractor"+" supply","tsc"+" platform","tsc"+" data"]
    hits=[]
    for p in root.rglob('*'):
        if not p.is_file() or '__pycache__' in p.parts or p.name==Path(__file__).name:continue
        try:t=p.read_text(encoding='utf-8').lower()
        except Exception:continue
        for b in banned:
            if b in t:hits.append((str(p),b))
    assert not hits,hits
