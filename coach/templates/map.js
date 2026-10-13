// Mini-map interactive : morts, kills, objectifs, trajet du jungler.
// Les données sont dans l'attribut data-map de chaque bloc .lolmap (générées par Python).
(function () {
  const SIZE = 15000;
  const ROLE_COLORS = { Top: "#e07a5f", Jungle: "#5fb38a", Mid: "#e9b949", ADC: "#4a8fd8", Support: "#b07cc6" };
  const OBJ = { DRAGON: "D", BARON_NASHOR: "N", RIFTHERALD: "H", HORDE: "L", ATAKHAN: "A",
                TOWER_BUILDING: "T", INHIBITOR_BUILDING: "I" };
  const NS = "http://www.w3.org/2000/svg";
  const px = (x) => (x / SIZE) * 1000;
  const py = (y) => 1000 - (y / SIZE) * 1000;
  const el = (tag, attrs, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  };
  const mmss = (t) => `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;

  function background(svg, img) {
    if (img) {
      el("image", { href: img, x: 0, y: 0, width: 1000, height: 1000, preserveAspectRatio: "none" }, svg);
      el("rect", { x: 0, y: 0, width: 1000, height: 1000, fill: "rgba(0,0,0,.25)" }, svg);
      return;
    }
    // Carte simplifiée si l'image Riot n'est pas disponible
    el("rect", { x: 0, y: 0, width: 1000, height: 1000, rx: 18, fill: "#1f3a2c" }, svg);
    el("path", { d: "M90 920 L90 90 L910 90", stroke: "#8a7a55", "stroke-width": 46, fill: "none", opacity: .55 }, svg);
    el("path", { d: "M90 910 L910 910 L910 90", stroke: "#8a7a55", "stroke-width": 46, fill: "none", opacity: .55 }, svg);
    el("path", { d: "M120 880 L880 120", stroke: "#8a7a55", "stroke-width": 46, opacity: .55 }, svg);
    el("path", { d: "M110 110 L890 890", stroke: "#2f6b8f", "stroke-width": 60, opacity: .55 }, svg);
    el("circle", { cx: 70, cy: 930, r: 95, fill: "#2b5f9e", opacity: .6 }, svg);
    el("circle", { cx: 930, cy: 70, r: 95, fill: "#9e2b2b", opacity: .6 }, svg);
  }

  function render(box) {
    const data = JSON.parse(box.dataset.map);
    const img = box.dataset.img || "";
    const layers = (box.dataset.layers || "deaths,kills,objectives").split(",");
    const state = { layer: layers[0], player: "Tous", period: "all", game: 0 };
    const players = [...new Set([...data.deaths, ...data.kills].map((d) => d[4]))];

    const controls = document.createElement("div");
    controls.className = "map-controls";
    const svg = el("svg", { viewBox: "0 0 1000 1000", class: "map-svg", role: "img" });
    const legend = document.createElement("div");
    legend.className = "map-legend";
    box.append(controls, svg, legend);

    const LABELS = { deaths: "Morts", kills: "Kills", objectives: "Objectifs", jungle: "Jungler 1-8 min" };
    function group(name, options, key) {
      const g = document.createElement("div");
      g.className = "seg";
      g.setAttribute("aria-label", name);
      options.forEach(([val, label]) => {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = label;
        b.onclick = () => { state[key] = val; draw(); };
        b.dataset.key = key; b.dataset.val = val;
        g.appendChild(b);
      });
      controls.appendChild(g);
    }
    group("Couche", layers.map((l) => [l, LABELS[l]]), "layer");
    group("Joueur", [["Tous", "Tous"], ...players.map((p) => [p, p])], "player");
    group("Période", [["all", "Toute la partie"], ["early", "< 15 min"], ["late", "15 min et +"]], "period");
    if (layers.includes("jungle") && data.jungle.length) {
      group("Partie", data.jungle.map((j, i) => [i, `Partie ${j.game}${j.win ? " ✓" : " ✗"}`]), "game");
    }

    function draw() {
      controls.querySelectorAll("button").forEach((b) => {
        b.classList.toggle("on", String(state[b.dataset.key]) === b.dataset.val);
        const hide = (b.dataset.key === "player" && !["deaths", "kills"].includes(state.layer)) ||
                     (b.dataset.key === "period" && state.layer === "jungle") ||
                     (b.dataset.key === "game" && state.layer !== "jungle");
        b.parentElement.style.display = hide ? "none" : "";
      });
      svg.innerHTML = "";
      background(svg, img);
      const okT = (t) => state.period === "all" || (state.period === "early" ? t < 900 : t >= 900);
      let count = 0;
      if (state.layer === "deaths" || state.layer === "kills") {
        const pts = data[state.layer].filter((d) => (state.player === "Tous" || d[4] === state.player) && okT(d[2]));
        const r = pts.length > 200 ? 9 : pts.length > 80 ? 12 : 15;   // points plus petits quand la carte est chargée
        pts.forEach((d) => {
            count++;
            const c = ROLE_COLORS[d[3]] || "#ccc";
            const early = d[2] < 900;
            const shape = state.layer === "deaths"
              ? el("circle", { cx: px(d[0]), cy: py(d[1]), r: r, fill: early ? c : "none", stroke: c, "stroke-width": r / 3, opacity: .85 }, svg)
              : el("rect", { x: px(d[0]) - r * .8, y: py(d[1]) - r * .8, width: r * 1.6, height: r * 1.6, transform: `rotate(45 ${px(d[0])} ${py(d[1])})`, fill: c, stroke: "#fff", "stroke-width": 2 }, svg);
            el("title", {}, shape).textContent = `${d[4]} (${d[3]}) · ${mmss(d[2])} · partie ${d[5]}`;
          });
        legend.innerHTML = Object.entries(ROLE_COLORS).map(([r, c]) => `<span><i style="background:${c}"></i>${r}</span>`).join("") +
          (state.layer === "deaths" ? `<span class="muted">● plein = avant 15 min · ○ vide = après</span>` : "") +
          `<span class="muted">${count} ${state.layer === "deaths" ? "mort(s)" : "kill(s)"}</span>`;
      } else if (state.layer === "objectives") {
        // Les objectifs tombent souvent au même endroit : on les regroupe avec un compteur
        const groups = {};
        (data.objectives || []).filter((o) => okT(o[2])).forEach((o) => {
          const key = `${o[3]}|${o[4]}|${Math.round(o[0] / 500)}|${Math.round(o[1] / 500)}`;
          (groups[key] = groups[key] || []).push(o);
        });
        Object.values(groups).forEach((list) => {
          const o = list[0];
          const c = o[4] ? "#3fb27f" : "#e05a4f";
          const dx = o[4] ? -23 : 23;   // nous à gauche, eux à droite au même endroit
          const g = el("g", {}, svg);
          el("circle", { cx: px(o[0]) + dx, cy: py(o[1]), r: 21, fill: c, stroke: "#fff", "stroke-width": 3, opacity: .92 }, g);
          const t = el("text", { x: px(o[0]) + dx, y: py(o[1]) + 8, "text-anchor": "middle", "font-size": 22, "font-weight": 700, fill: "#fff" }, g);
          t.textContent = OBJ[o[3]] || "?";
          if (list.length > 1) {
            el("circle", { cx: px(o[0]) + dx + 17, cy: py(o[1]) - 17, r: 13, fill: "#111", stroke: "#fff", "stroke-width": 2 }, g);
            const n = el("text", { x: px(o[0]) + dx + 17, y: py(o[1]) - 11, "text-anchor": "middle", "font-size": 16, "font-weight": 700, fill: "#fff" }, g);
            n.textContent = list.length;
          }
          el("title", {}, g).textContent = `${o[4] ? "Pris par nous" : "Pris par eux"} · ${o[3]} × ${list.length} · ` +
            list.map((x) => `${mmss(x[2])} (partie ${x[5]})`).join(", ");
          count += list.length;
        });
        legend.innerHTML = `<span><i style="background:#3fb27f"></i>Nous</span><span><i style="background:#e05a4f"></i>Eux</span>` +
          `<span class="muted">D dragon · N Nashor · H Héraut · L larves · T tour · I inhibiteur</span>`;
      } else if (state.layer === "jungle") {
        const j = data.jungle[state.game];
        if (j) {
          const pts = j.path.map((p) => `${px(p[0])},${py(p[1])}`).join(" ");
          el("polyline", { points: pts, fill: "none", stroke: ROLE_COLORS.Jungle, "stroke-width": 6, "stroke-dasharray": "14 8" }, svg);
          j.path.forEach((p) => {
            el("circle", { cx: px(p[0]), cy: py(p[1]), r: 19, fill: ROLE_COLORS.Jungle, stroke: "#fff", "stroke-width": 3 }, svg);
            const t = el("text", { x: px(p[0]), y: py(p[1]) + 8, "text-anchor": "middle", "font-size": 22, "font-weight": 700, fill: "#fff" }, svg);
            t.textContent = p[2];
          });
          legend.innerHTML = `<span class="muted">Position du jungler à chaque minute (1 à 8) · côté ${j.blue ? "bleu" : "rouge"} · ${j.win ? "victoire" : "défaite"}</span>`;
        }
      }
    }
    draw();
  }

  document.querySelectorAll(".lolmap").forEach(render);
})();
