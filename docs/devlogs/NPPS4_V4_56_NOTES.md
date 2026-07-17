# v4.56 — CN known banner assets and native Museum unlock

- Replaces arbitrary `npps4_*` home-banner asset identifiers with two identifiers already present in the CN client catalogue. The server aliases `s_ba_1718_1.png` to the data-transfer thumbnail and the exact honoka back-side path `wv_ba_01.png` to the manga thumbnail, including the `.imag` form used by KLB.
- Keeps the working dynamic type-1 scouting pages and their exact target IDs.
- Restores `museum_unlock_policy = "all"`, limited strictly to the 16 native CN Museum rows. The removed 1360-row GL transplant is not restored.
- Android/PC Python trees are synchronized.
