"""
In-memory stand-in for the Resolver CE data-entry API, used by the portal end-to-end test.
It reproduces the behaviours the portal must cope with: POST /new on an existing entry and PUT both merge by (linktype, hreflang, context), DELETE removes links, one record (removeRecord, ADR 0023) or the whole document;
PUT and a DELETE of links with qualifiers no record of the key has answer 404;
informativeQualifiers are kept like the real API does, and a registration with AI 21 plus AI 22 or
AI 10 is refused (GS1-Conformant Resolver 1.2.1, section 2.5.9, rule 2); If-Match / If-None-Match on a write
are checked against the record's revision and a write answers the new one (ADR 0058).
Bearer token: "tok".
"""
# Stands in for the Resolver CE data entry API (what matters: upsert and PUT merge links, partial DELETE)
import copy
import hashlib
import json
import re
from flask import Flask, request, jsonify
app = Flask(__name__)
DB = {}
def key(l): return (l.get("linktype"), tuple(sorted(l.get("hreflang") or [])), tuple(sorted(l.get("context") or [])))
def qm(a,b):
    n=lambda q: sorted((k,v) for i in (q or []) for k,v in i.items()); return n(a)==n(b)
def auth():
    return request.headers.get("Authorization")=="Bearer tok"
def v3(did):
    d=DB[did]; out=[]
    for e in d["entries"]:
        it={"anchor":"/"+did.replace("_","/",1),"itemDescription":e["itemDescription"],"defaultLinktype":d["default"],"links":copy.deepcopy(e["links"])}
        if e["qualifiers"]: it["qualifiers"]=e["qualifiers"]
        if e.get("informative"): it["informativeQualifiers"]=copy.deepcopy(e["informative"])
        out.append(it)
    return out
def rev(entry):            # revision.of() of the portal and the data entry API (ADR 0058)
    if entry is None: return None
    content={n:entry.get(n) or e() for n,e in (("qualifiers",list),("itemDescription",str),("links",list),("informativeQualifiers",list))}
    return hashlib.sha256(json.dumps(content,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()[:20]
def tags(h):
    if not h or not h.strip(): return None
    out=[p.strip()[2:] if p.strip().startswith("W/") else p.strip() for p in h.split(",")]
    return [p.strip().strip('"') for p in out if p.strip().strip('"')] or None
def entry_of(did,qualifiers):
    return next((e for e in v3(did) if qm(e.get("qualifiers"),qualifiers)),None) if did in DB else None
def failed(did,qualifiers):
    """A 412 answer when the request's If-Match / If-None-Match do not hold for the record, else None."""
    im,inm=tags(request.headers.get("If-Match")),tags(request.headers.get("If-None-Match"))
    cur=rev(entry_of(did,qualifiers))
    bad=(im is not None and (cur is None or ("*" not in im and cur not in im))) or \
        (inm is not None and cur is not None and ("*" in inm or cur in inm))
    return (jsonify(response_status=412,error="Record changed since it was read",revision=cur),412) if bad else None
def did_of(doc): return doc["anchor"].split("/")[-2]+"_"+doc["anchor"].split("/")[-1]
def rule2(qualifiers):
    ais={k for i in (qualifiers or []) for k in i}
    return "21" in ais and bool(ais & {"22","10"})
KEYS={"00","01","253","255","401","402","414","415","417","8003","8004","8006","8010","8013","8017","8018"}
def bad_anchor(doc):   # ADR 0049: /AI/value, a primary key, printable ASCII without "/" or space
    m=re.fullmatch(r"/([0-9]{2,4})/([!-.0-~]+)",doc.get("anchor") or "") if isinstance(doc,dict) else None
    return not m or m.group(1) not in KEYS
def upsert(doc):
    did=doc["anchor"].split("/")[-2]+"_"+doc["anchor"].split("/")[-1]
    assert not rule2(doc.get("qualifiers")), "rule 2 of section 2.5.9"
    assert doc["defaultLinktype"] in [l["linktype"] for l in doc["links"]], "defaultLink KeyError"
    ent={"qualifiers":doc.get("qualifiers",[]),"itemDescription":doc["itemDescription"],"links":copy.deepcopy(doc["links"]),
         "informative":copy.deepcopy(doc.get("informativeQualifiers") or [])}
    if did in DB:
        for e in DB[did]["entries"]:
            if qm(e["qualifiers"],ent["qualifiers"]):
                for nl in ent["links"]:
                    m=[i for i,l in enumerate(e["links"]) if key(l)==key(nl)]
                    if m: e["links"][m[0]].update(nl)
                    else: e["links"].append(nl)
                e["itemDescription"]=ent["itemDescription"]
                if "informativeQualifiers" in doc: e["informative"]=ent["informative"]
                return 200
        DB[did]["entries"].append(ent); return 200
    DB[did]={"default":doc["defaultLinktype"],"entries":[ent]}; return 201
@app.post("/api/new")
def new():
    if not auth(): return "no",403
    d=request.json
    if isinstance(d,list):
        if any(bad_anchor(x) for x in d): return jsonify(response_status=400,error="anchor"),400
        if any(rule2(x.get("qualifiers")) for x in d): return jsonify(response_status=400,error="rule 2"),400
        for x in d:
            f=failed(did_of(x),x.get("qualifiers",[]))
            if f: return f
        for x in d: upsert(x)
        return jsonify([{"ok":1}]),201
    if bad_anchor(d): return jsonify(response_status=400,error="anchor"),400
    if rule2(d.get("qualifiers")): return jsonify(response_status=400,error="rule 2"),400
    f=failed(did_of(d),d.get("qualifiers",[]))
    if f: return f
    s=upsert(d); return jsonify({"entry":"x","result":{"response_status":s},"revision":rev(entry_of(did_of(d),d.get("qualifiers",[])))}),s
@app.route("/api/<c>/<v>",methods=["GET","PUT","DELETE"])
def doc(c,v):
    if not auth(): return "no",403
    if "_" in c: return jsonify(response_status=400,error="path"),400
    did=f"{c}_{v}"
    d=request.get_json(silent=True)
    remove=request.method=="DELETE" and isinstance(d,dict) and "removeRecord" in d
    if remove and not (d["removeRecord"] is True and "links" not in d and isinstance(d.get("qualifiers",[]),list)
            and all(isinstance(q,dict) and len(q)==1 and all(isinstance(v,str) for v in q.values()) for q in d.get("qualifiers",[]))):
        return jsonify(response_status=400,error="removeRecord: true, qualifiers, no links"),400
    if request.method=="DELETE" and isinstance(d,dict) and request.content_length and not remove and not (
            isinstance(d.get("links"),list) and d["links"] and all(isinstance(l,dict) for l in d["links"])):
        return jsonify(response_status=400,error="a DELETE body must name links"),400
    if request.method!="GET" and d:
        f=failed(did,d.get("qualifiers",[]))
        if f: return f
    if did not in DB: return jsonify(response_status=404,error="nf"),404
    if request.method=="GET": return jsonify(data=v3(did),response_status=200)
    ents=DB[did]["entries"]
    idx=next((i for i,e in enumerate(ents) if qm(e["qualifiers"],(d or {}).get("qualifiers",[]))),None)
    if idx is None and (request.method=="PUT" or remove or (d and d.get("links"))):
        return jsonify(response_status=404,error="Record not found"),404
    if request.method=="PUT":
        e=ents[idx]
        if "itemDescription" in d: e["itemDescription"]=d["itemDescription"]
        if "defaultLinktype" in d: DB[did]["default"]=d["defaultLinktype"]
        if "informativeQualifiers" in d: e["informative"]=copy.deepcopy(d["informativeQualifiers"] or [])
        for nl in d.get("links",[]):
            m=[i for i,l in enumerate(e["links"]) if key(l)==key(nl)]
            if m: e["links"][m[0]].update(nl)
            else: e["links"].append(nl)
        return jsonify(response_status=200,revision=rev(entry_of(did,d.get("qualifiers",[]))))
    if remove:                     # one record removed, the key's others kept; the document goes with its last
        ents.pop(idx)
        if not ents: del DB[did]
        return jsonify(response_status=200,removed=1,remaining=len(ents),revision=None)
    if d and d.get("links"):
        e=ents[idx]; n=0
        for rl in d["links"]:
            m=[i for i,l in enumerate(e["links"]) if key(l)==key(rl)]
            if m: e["links"].pop(m[0]); n+=1
        if not n: return jsonify(response_status=404,error="none"),404
        assert e["links"], "empty linkset would crash"
        return jsonify(response_status=200,revision=rev(entry_of(did,d.get("qualifiers",[]))))
    del DB[did]; return jsonify(response_status=200)
@app.get("/api/summary")
def summary():
    if not auth(): return "no",403
    lines=[]
    for did in sorted(DB):
        for e in v3(did):
            line={"anchor":e["anchor"],"itemDescription":e["itemDescription"],"defaultLinktype":e["defaultLinktype"],"linkCount":len(e["links"])}
            if e.get("qualifiers"): line["qualifiers"]=e["qualifiers"]
            if e.get("informativeQualifiers"): line["informativeQualifiers"]=e["informativeQualifiers"]
            if request.args.get("links")=="true": line["links"]=e["links"]
            lines.append(line)
    if not lines: return jsonify(response_status=404,error="none"),404
    return jsonify(response_status=200,data=lines)
@app.post("/api/validate")
def validate():
    if not auth(): return "", 401
    d = request.get_json()
    items = d if isinstance(d, list) else [d]
    return jsonify(response_status=200, problems=[{"item": i, "error": "rule 2"} for i, x in enumerate(items, 1)
                                                  if rule2(x.get("qualifiers"))])
@app.get("/api/heartbeat")
def hb(): return {"response_message":"ok"}
