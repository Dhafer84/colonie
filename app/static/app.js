// Colonie spatiale — interface (JavaScript vanilla, sans build)
//
// Le serveur fait foi : l'interface récupère l'état via /api/etat, puis
// l'extrapole chaque seconde avec les taux par heure pour que les compteurs
// bougent, et redemande l'état toutes les 30 s (ou quand un chantier se termine,
// ou quand une ressource va s'épuiser).

"use strict";

const ICONES_RESSOURCES = { oxygene: "💨", energie: "⚡", nourriture: "🥕", materiaux: "🧱" };
const ICONES_BATIMENTS = {
  panneau_solaire: "☀️", generateur_o2: "🌀", serre: "🌿", mine: "⛏️", habitat: "🏠", entrepot: "📦",
};
const ICONES_JOURNAL = {
  penurie_debut: "⚠️", penurie_fin: "✅", construction: "🏗️", deblocage: "🔓", objectif: "🏆", hibernation: "💤", import: "📂",
};
const RAFRAICHISSEMENT = 30_000;     // ms
const NOUVEL_ESSAI = 10_000;         // ms, après une erreur réseau
const SEUIL_RAPPORT = 10 * 60;       // s : rapport d'absence au-delà de 10 min
const SEUIL_PRESQUE_VIDE = 2 * 3600; // s : alerte visuelle si une ressource sera vide avant

const nombre0 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const nombre1 = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nombreTaux = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1, signDisplay: "exceptZero" });

let vue = null;          // dernière réponse du serveur
let recuA = 0;           // Date.now() à la réception de `vue`
let enCours = false;     // une requête /api/etat est en vol
let minuteur = null;     // prochain rafraîchissement
const refs = {};         // éléments construits une seule fois

// --- Outils ------------------------------------------------------------------

function $(id) { return document.getElementById(id); }

function el(tag, classe, texte) {
  const e = document.createElement(tag);
  if (classe) e.className = classe;
  if (texte !== undefined) e.textContent = texte;
  return e;
}

function texte(e, valeur) {
  if (e.textContent !== valeur) e.textContent = valeur;
}

function majuscule(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

function deuxChiffres(n) { return String(n).padStart(2, "0"); }

/** Durée lisible. `precis` garde les secondes sous l'heure (comptes à rebours). */
function formatDuree(secondes, precis = false) {
  const s = Math.max(0, Math.round(secondes));
  if (s < 60) return precis ? `${s} s` : "moins d'1 min";
  if (s < 3600) {
    const m = Math.floor(s / 60), r = s % 60;
    if (!precis) return `${Math.ceil(s / 60)} min`;
    return r ? `${m} min ${deuxChiffres(r)} s` : `${m} min`;
  }
  if (s < 86400) {
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return m ? `${h} h ${deuxChiffres(m)}` : `${h} h`;
  }
  const j = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600);
  return h ? `${j} j ${h} h` : `${j} j`;
}

function ilYa(t, maintenant) {
  const ecart = maintenant - t;
  if (ecart < 60) return "à l'instant";
  if (ecart < 86400) return `il y a ${formatDuree(ecart)}`;
  return new Date(t * 1000).toLocaleString("fr-FR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function nomRessource(r) { return majuscule(vue.noms_ressources[r]); }

function texteEffets(effets) {
  const morceaux = [];
  for (const [r, v] of Object.entries(effets.produit)) morceaux.push(`+${nombre1.format(v)} ${ICONES_RESSOURCES[r]}/h`);
  for (const [r, v] of Object.entries(effets.consomme)) morceaux.push(`−${nombre1.format(v)} ${ICONES_RESSOURCES[r]}/h`);
  if (effets.places) morceaux.push(`${effets.places} places`);
  if (effets.stockage) morceaux.push(`+${nombre0.format(effets.stockage)} de stockage`);
  if (effets.postes) morceaux.push(`${effets.postes} 🧑‍🚀 au travail`);
  return morceaux.join(" · ") || "—";
}

// --- Réseau ------------------------------------------------------------------

async function appeler(url, options = {}) {
  const reponse = await fetch(url, { cache: "no-store", ...options });
  let corps = null;
  try { corps = await reponse.json(); } catch { /* réponse non JSON (proxy, panne…) */ }
  if (!reponse.ok) {
    const detail = corps && typeof corps.detail === "string" ? corps.detail : `Erreur ${reponse.status}`;
    const erreur = new Error(detail);
    erreur.statut = reponse.status;
    throw erreur;
  }
  return corps;
}

function poster(url, donnees) {
  return appeler(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(donnees),
  });
}

async function rafraichir() {
  if (enCours) return;
  enCours = true;
  try {
    const v = await appeler("/api/etat");
    masquerConnexion();
    recevoir(v);
    if (v.rapport && v.rapport.duree >= SEUIL_RAPPORT) afficherRapport(v.rapport);
  } catch (erreur) {
    afficherConnexion(erreur);
    planifier(NOUVEL_ESSAI);
  } finally {
    enCours = false;
  }
}

function afficherConnexion(erreur) {
  const bandeau = $("connexion");
  bandeau.textContent = navigator.onLine === false
    ? "📡 Hors ligne : les chiffres affichés ne sont plus à jour."
    : `📡 Liaison avec la colonie perdue (${erreur.message}). Nouvel essai dans quelques secondes…`;
  bandeau.hidden = false;
}

function masquerConnexion() { $("connexion").hidden = true; }

/** Prochain rafraîchissement : 30 s au plus, plus tôt si quelque chose va changer. */
function planifier(delai) {
  clearTimeout(minuteur);
  if (delai === undefined) {
    delai = RAFRAICHISSEMENT;
    const est = estime();
    if (vue.chantier) delai = Math.min(delai, (vue.chantier.fin - est.maintenant) * 1000 + 500);
    for (const [r, taux] of Object.entries(vue.taux)) {
      if (taux < 0 && est.ressources[r] > 0) {
        delai = Math.min(delai, (est.ressources[r] / -taux) * 3600 * 1000 + 500);
      }
    }
    delai = Math.max(delai, 1000);
  }
  minuteur = setTimeout(() => (document.hidden ? planifier(NOUVEL_ESSAI) : rafraichir()), delai);
}

function recevoir(v) {
  vue = v;
  recuA = Date.now();
  if (!refs.construit) construireInterface();
  majJournal();
  tic();
  planifier();
}

// --- Extrapolation entre deux réponses du serveur ---------------------------

function estime() {
  const dt = (Date.now() - recuA) / 1000;
  const heures = dt / 3600;
  const ressources = {};
  for (const [r, base] of Object.entries(vue.ressources)) {
    const taux = vue.taux[r];
    let valeur = base + taux * heures;
    // Comme le moteur : la production s'arrête au plafond, sans détruire un excédent
    if (taux > 0) valeur = Math.min(valeur, Math.max(vue.capacite, base));
    ressources[r] = Math.max(0, valeur);
  }
  let colons = vue.colons;
  const crise = vue.ressources.nourriture <= 0 || vue.ressources.oxygene <= 0;
  if (!crise && colons < vue.capacite_colons) {
    colons = Math.min(vue.capacite_colons, colons + vue.croissance_colons * heures);
  }
  const sansPenurie = Object.keys(vue.penuries).length ? vue.sans_penurie : vue.sans_penurie + dt;
  return { maintenant: vue.maintenant + dt, ressources, colons, sansPenurie, crise };
}

// --- Construction de l'interface (une seule fois) ---------------------------

function construireInterface() {
  const contenu = $("contenu");
  contenu.replaceChildren($("modele-contenu").content.cloneNode(true));
  contenu.removeAttribute("aria-busy");

  // Objectif
  const objectif = $("objectif");
  refs.objectif = {
    entete: el("div", "objectif-entete"),
    titre: el("div", "objectif-titre"),
    description: el("p", "objectif-description"),
    barre: el("span"),
    progression: el("div", "objectif-progression"),
  };
  const barreObjectif = el("div", "barre");
  barreObjectif.append(refs.objectif.barre);
  objectif.append(refs.objectif.entete, refs.objectif.titre, refs.objectif.description,
    barreObjectif, refs.objectif.progression);

  // Ressources + colons
  refs.ressources = {};
  const grille = $("ressources");
  for (const r of [...Object.keys(vue.ressources), "colons"]) {
    const tuile = el("div", "ressource");
    const nom = r === "colons" ? "🧑‍🚀 Colons" : `${ICONES_RESSOURCES[r]} ${nomRessource(r)}`;
    const valeur = el("div", "ressource-valeur");
    const nombre = el("span");
    const capacite = el("small");
    valeur.append(nombre, " ", capacite);
    const barre = el("div", "barre");
    const remplissage = el("span");
    barre.append(remplissage);
    const taux = el("div", "ressource-taux");
    const indice = el("div", "ressource-indice");
    tuile.append(el("div", "ressource-nom", nom), valeur, taux, barre, indice);
    grille.append(tuile);
    refs.ressources[r] = { tuile, nombre, capacite, taux, remplissage, indice };
  }

  // Chantier
  refs.chantier = { titre: el("strong"), reste: el("span", "chantier-reste"), barre: el("span") };
  const ligne = el("div", "chantier-ligne");
  ligne.append(refs.chantier.titre, refs.chantier.reste);
  const barreChantier = el("div", "barre");
  barreChantier.append(refs.chantier.barre);
  $("chantier").append(ligne, barreChantier);

  // Bâtiments
  refs.batiments = {};
  const liste = $("batiments");
  for (const b of vue.batiments) {
    const carte = el("article", "batiment");
    const titre = el("div", "batiment-titre");
    const niveau = el("span", "batiment-niveau");
    titre.append(el("span", "batiment-nom", b.nom), niveau);
    const details = el("div", "batiment-details");
    const actuel = el("div");
    const suivant = el("div");
    details.append(actuel, suivant);
    const action = el("div", "batiment-action");
    const bouton = el("button", "bouton bouton-principal");
    bouton.type = "button";
    bouton.addEventListener("click", () => construireBatiment(b.id, bouton));
    const raison = el("span", "batiment-raison");
    action.append(bouton, raison);
    carte.append(el("div", "batiment-icone", ICONES_BATIMENTS[b.id] || "🏢"), titre,
      el("div", "batiment-description", b.description), details, action);
    liste.append(carte);
    refs.batiments[b.id] = { carte, niveau, actuel, suivant, bouton, raison };
  }

  refs.construit = true;
}

// --- Mises à jour ------------------------------------------------------------

/** Appelée chaque seconde : met à jour tout ce qui dépend du temps. */
function tic() {
  if (!vue) return;
  const est = estime();
  majObjectif(est);
  majAlertes(est);
  majRessources(est);
  majChantier(est);
  majBatiments(est);
}

function majObjectif(est) {
  const o = vue.objectif;
  const r = refs.objectif;
  if (!o) {
    texte(r.entete, `Objectifs : ${vue.objectifs_total} / ${vue.objectifs_total}`);
    texte(r.titre, "🎉 Tous les objectifs sont accomplis");
    texte(r.description, "La colonie est autonome. Continue à l'agrandir !");
    texte(r.progression, "");
    r.barre.style.width = "100%";
    return;
  }
  let actuel = o.actuel, progression;
  if (o.type === "colons") {
    actuel = Math.floor(est.colons + 1e-9);
    progression = `${actuel} / ${o.cible} colons`;
  } else if (o.type === "sans_penurie") {
    actuel = est.sansPenurie;
    progression = `${formatDuree(actuel)} / ${formatDuree(o.cible)} sans pénurie`;
  } else {
    progression = `Niveau ${actuel} / ${o.cible}`;
  }
  texte(r.entete, `Objectif ${o.numero} / ${vue.objectifs_total} · récompense +${o.recompense} 🧱`);
  texte(r.titre, o.titre);
  texte(r.description, o.description);
  texte(r.progression, progression);
  r.barre.style.width = `${Math.min(100, (actuel / o.cible) * 100)}%`;
}

function majAlertes(est) {
  const messages = [];
  const debut = (r) => formatDuree(est.maintenant - vue.penuries[r]);
  if ("energie" in vue.penuries) {
    messages.push(["alerte", `⚡ Pénurie d'énergie depuis ${debut("energie")} : les bâtiments tournent à ${Math.round(vue.efficacite_energie * 100)} %. Construis ou améliore un panneau solaire.`]);
  }
  if ("nourriture" in vue.penuries) {
    messages.push(["alerte", `🥕 Famine depuis ${debut("nourriture")} : production réduite de moitié et des colons quittent la colonie.`]);
  }
  if ("oxygene" in vue.penuries) {
    messages.push(["alerte", `💨 Plus d'oxygène depuis ${debut("oxygene")} : des colons quittent la colonie.`]);
  }
  if (vue.efficacite_ouvriers < 1) {
    messages.push(["info", `🧑‍🚀 Il manque des bras : ${vue.postes} postes pour ${nombre1.format(vue.colons)} colons, les postes produisent à ${Math.round(vue.efficacite_ouvriers * 100)} %.`]);
  }
  const conteneur = $("alertes");
  const signature = messages.map((m) => m.join(":")).join("|");
  if (conteneur.dataset.signature === signature) return;
  conteneur.dataset.signature = signature;
  conteneur.replaceChildren(...messages.map(([type, message]) => {
    const bandeau = el("div", `bandeau bandeau-${type}`, message);
    if (type === "alerte") bandeau.setAttribute("role", "alert");
    return bandeau;
  }));
}

function majRessources(est) {
  for (const [r, valeur] of Object.entries(est.ressources)) {
    const t = refs.ressources[r];
    const taux = vue.taux[r];
    const penurie = r in vue.penuries;
    texte(t.nombre, nombre0.format(Math.floor(valeur)));
    texte(t.capacite, `/ ${nombre0.format(vue.capacite)}`);
    texte(t.taux, `${nombreTaux.format(taux)}/h`);
    t.taux.className = `ressource-taux ${taux > 0.05 ? "positif" : taux < -0.05 ? "negatif" : "neutre"}`;
    t.remplissage.style.width = `${Math.min(100, (valeur / vue.capacite) * 100)}%`;

    let indice = "";
    let presqueVide = false;
    if (penurie) {
      indice = r === "energie" ? "Insuffisante !" : "Épuisé !";
    } else if (taux < 0 && valeur > 0) {
      const reste = (valeur / -taux) * 3600;
      indice = `vide dans ${formatDuree(reste)}`;
      presqueVide = reste < SEUIL_PRESQUE_VIDE;
    } else if (valeur >= vue.capacite) {
      indice = "stock plein";
    } else if (taux > 0) {
      indice = `plein dans ${formatDuree(((vue.capacite - valeur) / taux) * 3600)}`;
    }
    texte(t.indice, indice);
    t.tuile.classList.toggle("en-penurie", penurie);
    t.tuile.classList.toggle("presque-vide", presqueVide);
  }

  // Colons
  const t = refs.ressources.colons;
  texte(t.nombre, nombre1.format(est.colons));
  texte(t.capacite, `/ ${vue.capacite_colons}`);
  let taux, classe;
  if (est.crise) {
    taux = "départs en cours"; classe = "negatif";
  } else if (est.colons >= vue.capacite_colons) {
    taux = "habitats pleins"; classe = "neutre";
  } else {
    taux = `${nombreTaux.format(vue.croissance_colons)}/h`; classe = "positif";
  }
  texte(t.taux, taux);
  t.taux.className = `ressource-taux ${classe}`;
  t.remplissage.style.width = `${Math.min(100, (est.colons / vue.capacite_colons) * 100)}%`;
  texte(t.indice, vue.postes ? `${vue.postes} postes de travail` : "");
  t.tuile.classList.toggle("en-penurie", est.crise);
}

function majChantier(est) {
  const section = $("chantier");
  const c = vue.chantier;
  section.hidden = !c;
  if (!c) return;
  const nom = vue.batiments.find((b) => b.id === c.batiment).nom;
  texte(refs.chantier.titre, `🏗️ ${nom} → niveau ${c.niveau}`);
  const reste = c.fin - est.maintenant;
  texte(refs.chantier.reste, reste > 0 ? formatDuree(reste, true) : "finalisation…");
  const avance = (est.maintenant - c.debut) / (c.fin - c.debut);
  refs.chantier.barre.style.width = `${Math.max(0, Math.min(100, avance * 100))}%`;
}

function majBatiments(est) {
  const materiaux = est.ressources.materiaux;
  for (const b of vue.batiments) {
    const r = refs.batiments[b.id];
    const enConstruction = vue.chantier && vue.chantier.batiment === b.id;
    texte(r.niveau, b.niveau ? `niv. ${b.niveau}` : "pas construit");
    texte(r.actuel, b.niveau ? `Actuel : ${texteEffets(b.effets)}` : "");
    r.actuel.hidden = !b.niveau;
    texte(r.suivant, b.prochain ? `Niv. ${b.prochain.niveau} : ${texteEffets(b.prochain.effets)}` : "Niveau maximum atteint");

    let raison, actif = false, visible = true;
    if (!b.debloque) {
      raison = `🔒 Se débloque à ${b.deblocage.colons} colons`;
      visible = false;
    } else if (!b.prochain) {
      raison = "";
      visible = false;
    } else if (enConstruction) {
      raison = "Chantier en cours…";
    } else if (vue.chantier) {
      raison = "Un autre chantier est en cours";
    } else if (materiaux < b.prochain.cout) {
      const manque = b.prochain.cout - materiaux;
      const tauxMat = vue.taux.materiaux;
      raison = `Il manque ${nombre0.format(Math.ceil(manque))} 🧱`
        + (tauxMat > 0 ? ` (≈ ${formatDuree((manque / tauxMat) * 3600)})` : "");
    } else {
      raison = `⏱ ${formatDuree(b.prochain.duree, true)}`;
      actif = true;
    }
    if (b.prochain) {
      texte(r.bouton, `${b.niveau ? "Améliorer" : "Construire"} · ${nombre0.format(b.prochain.cout)} 🧱`);
    }
    r.bouton.hidden = !visible;
    if (!r.bouton.dataset.envoi) r.bouton.disabled = !actif;
    texte(r.raison, raison);
    r.carte.classList.toggle("verrouille", !b.debloque);
    r.carte.classList.toggle("en-construction", Boolean(enConstruction));
  }
}

function majJournal() {
  const liste = $("journal");
  if (!vue.journal.length) {
    liste.replaceChildren(el("li", "vide", "Rien à signaler pour l'instant."));
    return;
  }
  liste.replaceChildren(...vue.journal.map((ev) => {
    const ligne = el("li");
    const quand = el("time", "", ilYa(ev.t, vue.maintenant));
    quand.dateTime = new Date(ev.t * 1000).toISOString();
    ligne.append(el("span", "", ICONES_JOURNAL[ev.type] || "•"), el("span", "", ev.message), quand);
    return ligne;
  }));
}

// --- Rapport d'absence -------------------------------------------------------

function afficherRapport(rapport) {
  const fenetre = $("rapport");
  if (fenetre.open) return;
  const contenu = $("rapport-contenu");
  const intro = el("p", "", `Absence : ${formatDuree(rapport.duree)}. Voici ce qui s'est passé dans la colonie.`);

  const tableau = el("table", "bilan");
  const ligne = (nom, avant, apres, format) => {
    const tr = el("tr");
    const ecart = apres - avant;
    const delta = el("td", Math.abs(ecart) < 0.5 ? "neutre" : ecart > 0 ? "positif" : "negatif",
      Math.abs(ecart) < 0.5 ? "=" : nombreTaux.format(format === 1 ? Math.round(ecart * 10) / 10 : Math.round(ecart)));
    tr.append(el("td", "", nom), el("td", "", `${format === 1 ? nombre1.format(avant) : nombre0.format(avant)} → ${format === 1 ? nombre1.format(apres) : nombre0.format(apres)}`), delta);
    return tr;
  };
  for (const r of Object.keys(rapport.ressources_avant)) {
    tableau.append(ligne(`${ICONES_RESSOURCES[r]} ${nomRessource(r)}`, rapport.ressources_avant[r], rapport.ressources_apres[r], 0));
  }
  tableau.append(ligne("🧑‍🚀 Colons", rapport.colons_avant, rapport.colons_apres, 1));

  const elements = [intro, tableau];
  const evenements = rapport.evenements;
  if (evenements.length) {
    const max = 12;
    const liste = el("ul", "rapport-evenements");
    for (const ev of evenements.slice(0, max)) {
      liste.append(el("li", "", `${ICONES_JOURNAL[ev.type] || "•"} ${ev.message}`));
    }
    if (evenements.length > max) liste.append(el("li", "neutre", `… et ${evenements.length - max} autres événements (voir le journal)`));
    elements.push(liste);
  } else {
    elements.push(el("p", "neutre", "Aucun événement particulier."));
  }
  contenu.replaceChildren(...elements);
  fenetre.showModal();
}

// --- Actions -----------------------------------------------------------------

function notifier(message, erreur = false) {
  const n = $("notification");
  n.textContent = message;
  n.classList.toggle("erreur", erreur);
  n.hidden = false;
  clearTimeout(notifier.minuteur);
  notifier.minuteur = setTimeout(() => { n.hidden = true; }, 3500);
}

async function construireBatiment(id, bouton) {
  bouton.disabled = true;
  bouton.dataset.envoi = "1";
  try {
    const v = await poster("/api/construire", { batiment: id });
    recevoir(v);
    const c = v.chantier;
    const nom = v.batiments.find((b) => b.id === id).nom;
    notifier(`🏗️ Chantier lancé : ${nom} niveau ${c.niveau} (${formatDuree(c.fin - c.debut, true)})`);
  } catch (erreur) {
    notifier(erreur.message, true);
    rafraichir();
  } finally {
    delete bouton.dataset.envoi;
    tic();
  }
}

async function nouvellePartie() {
  if (!confirm("Fonder une nouvelle colonie ? La partie actuelle sera définitivement perdue.")) return;
  try {
    const v = await poster("/api/nouvelle-partie", { confirmer: true });
    $("menu").close();
    recevoir(v);
    notifier("🚀 Nouvelle colonie fondée. Bonne chance !");
  } catch (erreur) {
    notifier(erreur.message, true);
  }
}

async function exporter() {
  try {
    const reponse = await fetch("/api/export", { cache: "no-store" });
    if (!reponse.ok) throw new Error(`Erreur ${reponse.status}`);
    const disposition = reponse.headers.get("Content-Disposition") || "";
    const nom = (disposition.match(/filename="([^"]+)"/) || [])[1] || "colonie.json";
    const lien = el("a");
    lien.href = URL.createObjectURL(await reponse.blob());
    lien.download = nom;
    document.body.append(lien);
    lien.click();
    lien.remove();
    setTimeout(() => URL.revokeObjectURL(lien.href), 10_000);
    notifier(`💾 Partie exportée : ${nom}`);
  } catch (erreur) {
    notifier(`Export impossible : ${erreur.message}`, true);
  }
}

async function importer(fichier) {
  if (!fichier) return;
  try {
    let donnees;
    try { donnees = JSON.parse(await fichier.text()); } catch { throw new Error("Ce fichier n'est pas du JSON valide."); }
    if (!confirm("Remplacer la partie actuelle par celle du fichier ? La partie actuelle sera perdue.")) return;
    const v = await poster("/api/import", donnees);
    $("menu").close();
    recevoir(v);
    notifier("📂 Partie importée.");
    if (v.rapport && v.rapport.duree >= SEUIL_RAPPORT) afficherRapport(v.rapport);
  } catch (erreur) {
    notifier(erreur.message, true);
  } finally {
    $("fichier-import").value = "";
  }
}

// --- Démarrage ---------------------------------------------------------------

function demarrer() {
  $("bouton-menu").addEventListener("click", () => $("menu").showModal());
  $("bouton-nouvelle").addEventListener("click", nouvellePartie);
  $("bouton-exporter").addEventListener("click", exporter);
  $("bouton-importer").addEventListener("click", () => $("fichier-import").click());
  $("fichier-import").addEventListener("change", (e) => importer(e.target.files[0]));
  document.addEventListener("visibilitychange", () => { if (!document.hidden) rafraichir(); });
  window.addEventListener("online", rafraichir);
  setInterval(tic, 1000);
  rafraichir();

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* HTTP simple : pas de PWA, le jeu marche quand même */ });
  }
}

demarrer();
