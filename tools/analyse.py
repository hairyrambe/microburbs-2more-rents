import sys, numpy as np, pandas as pd
sys.path.insert(0,'src'); import build_model as B, config as C
raw,_=B.load_adverts(); inp=B.load_input(); adv,_=B.clean_adverts(raw,inp)
adv["y"]=B.apply_index(adv,B.rent_index(adv))
a=adv.dropna(subset=["car","building_address"]).copy()
a=a[a["date"]>="2020-01-01"]
for keys in [["building_address","beds"],["building_address","beds","baths"]]:
    g=a.groupby(keys)
    a["yd"]=a["y"]-g["y"].transform("mean"); a["cd"]=a["car"]-g["car"].transform("mean")
    b=(a.yd*a.cd).sum()/(a.cd**2).sum()
    print(keys,"within-building log premium",round(b,4),"=> ~$",round((np.exp(b)-1)*900,1),"on $900")
# same flat, adverts with and without car (car status changed)
for beds,grp in a.groupby("beds"):
    if beds>3: continue
    g=grp.groupby(["building_address","beds"]); yd=grp.y-g.y.transform("mean"); cd=grp.car-g.car.transform("mean")
    b=(yd*cd).sum()/(cd**2).sum(); print("beds",int(beds),"premium %",round((np.exp(b)-1)*100,1),"n",len(grp), "median rent", grp.rent.median())
