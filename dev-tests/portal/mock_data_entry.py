"""
In-memory stand-in for the Resolver CE data-entry API, used by the portal end-to-end test.
It reproduces the behaviours the portal must cope with: POST /new appends links to an existing
entry, PUT merges by (linktype, hreflang, context), DELETE removes links or the whole document;
informativeQualifiers are kept like the real API does, and a registration with AI 21 plus AI 22 or
AI 10 is refused (GS1-Conformant Resolver 1.2.1, section 2.5.9, rule 2).
Bearer token: "tok".
"""
# Emula o data-entry do Resolver CE (semântica relevante: upsert com extend, PUT merge, DELETE parcial)
import copy
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
        it={"anchor":"/"+did.replace("_","/"),"itemDescription":e["itemDescription"],"defaultLinktype":d["default"],"links":copy.deepcopy(e["links"])}
        if e["qualifiers"]: it["qualifiers"]=e["qualifiers"]
        if e.get("informative"): it["informativeQualifiers"]=copy.deepcopy(e["informative"])
        out.append(it)
    return out
def rule2(qualifiers):
    ais={k for i in (qualifiers or []) for k in i}
    return "21" in ais and bool(ais & {"22","10"})
def upsert(doc):
    did=doc["anchor"].split("/")[-2]+"_"+doc["anchor"].split("/")[-1]
    assert not rule2(doc.get("qualifiers")), "rule 2 of section 2.5.9"
    assert doc["defaultLinktype"] in [l["linktype"] for l in doc["links"]], "defaultLink KeyError"
    ent={"qualifiers":doc.get("qualifiers",[]),"itemDescription":doc["itemDescription"],"links":copy.deepcopy(doc["links"]),
         "informative":copy.deepcopy(doc.get("informativeQualifiers") or [])}
    if did in DB:
        for e in DB[did]["entries"]:
            if qm(e["qualifiers"],ent["qualifiers"]):
                e["links"].extend(ent["links"])
                if "informativeQualifiers" in doc: e["informative"]=ent["informative"]
                return 200
        DB[did]["entries"].append(ent); return 200
    DB[did]={"default":doc["defaultLinktype"],"entries":[ent]}; return 201
@app.post("/api/new")
def new():
    if not auth(): return "no",403
    d=request.json
    if isinstance(d,list):
        if any(rule2(x.get("qualifiers")) for x in d): return jsonify(response_status=400,error="rule 2"),400
        for x in d: upsert(x)
        return jsonify([{"ok":1}]),201
    if rule2(d.get("qualifiers")): return jsonify(response_status=400,error="rule 2"),400
    s=upsert(d); return jsonify({"entry":"x","result":{"response_status":s}}),s
@app.route("/api/<c>/<v>",methods=["GET","PUT","DELETE"])
def doc(c,v):
    if not auth(): return "no",403
    did=f"{c}_{v}"
    if did not in DB: return jsonify(response_status=404,error="nf"),404
    if request.method=="GET": return jsonify(data=v3(did),response_status=200)
    d=request.get_json(silent=True)
    ents=DB[did]["entries"]
    idx=0
    for i,e in enumerate(ents):
        if qm(e["qualifiers"],(d or {}).get("qualifiers",[])): idx=i;break
    if request.method=="PUT":
        e=ents[idx]
        if "itemDescription" in d: e["itemDescription"]=d["itemDescription"]
        if "defaultLinktype" in d: DB[did]["default"]=d["defaultLinktype"]
        if "informativeQualifiers" in d: e["informative"]=copy.deepcopy(d["informativeQualifiers"] or [])
        for nl in d.get("links",[]):
            m=[i for i,l in enumerate(e["links"]) if key(l)==key(nl)]
            if m: e["links"][m[0]].update(nl)
            else: e["links"].append(nl)
        return jsonify(response_status=200)
    if d and d.get("links"):
        e=ents[idx]; n=0
        for rl in d["links"]:
            m=[i for i,l in enumerate(e["links"]) if key(l)==key(rl)]
            if m: e["links"].pop(m[0]); n+=1
        if not n: return jsonify(response_status=404,error="none"),404
        assert e["links"], "empty linkset would crash"
        return jsonify(response_status=200)
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
@app.get("/api/heartbeat")
def hb(): return {"response_message":"ok"}
