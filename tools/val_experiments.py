import sys, numpy as np, pandas as pd
sys.path.insert(0,'src'); import build_model as B, config as C
raw,_=B.load_adverts(); inp=B.load_input(); adv,_=B.clean_adverts(raw,inp)
tgt=B.prep_input(inp)
codes={"suburb":{s:i for i,s in enumerate(sorted(set(adv.suburb_n)|set(tgt.suburb_n)))},
       "ptype":{s:i for i,s in enumerate(sorted(set(adv.ptype_n)|set(tgt.ptype_n)))}}
cut=pd.Timestamp(C.VAL_START); tr=adv[adv.date<cut].copy(); va=adv[(adv.date>=cut)&adv.car.notna()].copy()
tr["y"]=B.apply_index(tr,B.rent_index(tr)); va["y"]=np.nan
Xtr=B.features(tr,tr,codes,"train"); Xva=B.features(va,tr,codes,"apply",as_of=tr.date.max())
m=B.new_model(list(Xtr.columns)).fit(Xtr,tr.y)
y=va.rent.values
def pred(X,c):
    X=X.copy(); X["car"]=c; X["own_car_changed"]=(X.own_prev_car!=X.car).astype(float).where(X.own_prev_car.notna()); return np.exp(m.predict(X))
p1,p0=pred(Xva,1.0),pred(Xva,0.0); p=np.where(va.car.values==1,p1,p0)
def s(p): e=np.abs(p-y); return round(np.median(e),2), round((e<=100).mean()*100,2)
print("as is", s(p), "median premium", np.median(p1-p0))
icar=va.gnaf.map(inp.set_index("gnaf_id").car_space).values
print("adverts whose parking differs from input car_space:", np.nansum(icar!=va.car.values), "of", len(va))
# alt: base on the input car status, premium as a fixed % for the other
pbase=np.where(icar==1,p1,p0); pbase=np.where(np.isnan(icar),p,pbase)
for beta in [0,0.03,0.05,0.08]:
    alt=pbase*np.exp(beta*(va.car.values-np.nan_to_num(icar,nan=va.car.values)))
    print("fixed premium",beta, s(np.maximum(alt, 0)))
for k in [0.97,0.98,0.99,1.0,1.01]: print("scale",k, s(p*k))
