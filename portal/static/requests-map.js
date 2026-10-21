"use strict";

/*
 * The map of requests on the Requests screen (Documentation/adr/0006-resolver-request-log.md, section 10): where the
 * requests of the screen's filters come from, roughly. Countries are shaded by their number of requests, each city the
 * resolver placed (its position to a tenth of a degree, from the GeoIP database) is a circle sized by its requests.
 * The wheel, a drag, the + and − buttons zoom and move; a click on a country zooms to it and lists its regions and
 * cities beside the map. Nothing is fetched from another site: d3 (ISC licence), topojson-client (ISC) and the
 * countries of Natural Earth through world-atlas (public domain, ISC) are files of the portal, loaded the first time
 * the map is opened.
 *
 * RequestsMap.render(box, data) with data = GET /portal/api/requests/places; texts through I18N.
 */
const RequestsMap = (() => {
  const FILES = { d3: "d3.min.js", topojson: "topojson-client.min.js", world: "world-countries.json", iso: "iso3166.json" };
  const EMPTY = "#E6EBF1", LOW = "#9DBBE6", HIGH = "#002C6C", CITY = "#F26334";
  let loading = null;

  function script(src) {
    return new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = src;
      tag.onload = resolve;
      tag.onerror = () => reject(new Error(src));
      document.head.append(tag);
    });
  }

  /* d3, topojson and the countries, once */
  function load() {
    loading ||= Promise.all([
      window.d3 ? null : script(FILES.d3),
      window.topojson ? null : script(FILES.topojson),
      fetch(FILES.world, { credentials: "same-origin" }).then(r => r.json()),
      fetch(FILES.iso, { credentials: "same-origin" }).then(r => r.json()),
    ]).then(([, , world, iso]) => {
      const numeric = {};
      Object.entries(iso).forEach(([alpha2, num]) => { numeric[num] = alpha2; });
      const countries = topojson.feature(world, world.objects.countries).features;
      countries.forEach(f => { f.properties.code = numeric[f.id] || null; });
      return { countries };
    });
    loading.catch(() => { loading = null; });
    return loading;
  }

  const nf = n => new Intl.NumberFormat(I18N.locale).format(n);

  function countryName(code) {
    try {
      return new Intl.DisplayNames([I18N.locale], { type: "region" }).of(code) || code;
    } catch {
      return code;
    }
  }

  function placeName(p) {
    return [p.city, p.region].filter(Boolean).join(", ") || countryName(p.country);
  }

  async function render(box, data) {
    const { countries } = await load();
    const width = Math.max(320, box.clientWidth || 800), height = Math.round(width * 0.5);
    const perCountry = new Map(data.countries.map(([code, n]) => [code, n]));
    const max = Math.max(1, ...perCountry.values());
    const shade = d3.scaleLog().domain([1, max === 1 ? 2 : max]).range([LOW, HIGH]).interpolate(d3.interpolateRgb);
    const placed = data.places.filter(p => p.position);
    const radius = d3.scaleSqrt().domain([1, Math.max(1, ...placed.map(p => p.requests))]).range([2.5, 14]);

    box.replaceChildren();
    const frame = document.createElement("div");
    frame.className = "map-frame";
    const tip = document.createElement("div");
    tip.className = "map-tip";
    tip.hidden = true;
    const side = document.createElement("aside");
    side.className = "map-side";
    side.setAttribute("aria-live", "polite");
    box.append(frame, side);

    const projection = d3.geoNaturalEarth1().fitExtent([[4, 4], [width - 4, height - 4]], { type: "Sphere" });
    const path = d3.geoPath(projection);
    const svg = d3.select(frame).append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`).attr("role", "img")
      .attr("aria-label", I18N.t("requests.mapLabel", { countries: nf(perCountry.size), places: nf(placed.length) }));
    const layer = svg.append("g");
    layer.append("path").attr("class", "map-sphere").attr("d", path({ type: "Sphere" }));
    const shapes = layer.append("g").selectAll("path").data(countries).join("path")
      .attr("class", "map-country").attr("d", path)
      .attr("data-code", f => f.properties.code || "")
      .attr("fill", f => perCountry.has(f.properties.code) ? shade(perCountry.get(f.properties.code)) : EMPTY);
    const dots = layer.append("g").selectAll("circle").data(placed).join("circle")
      .attr("class", "map-city")
      .attr("cx", p => projection([p.position[1], p.position[0]])[0])
      .attr("cy", p => projection([p.position[1], p.position[0]])[1])
      .attr("r", p => radius(p.requests)).attr("fill", CITY);

    const zoom = d3.zoom().scaleExtent([1, 40]).translateExtent([[0, 0], [width, height]])
      .on("zoom", e => {
        layer.attr("transform", e.transform);
        dots.attr("r", p => radius(p.requests) / Math.sqrt(e.transform.k));
        layer.selectAll(".map-country").attr("stroke-width", 0.5 / e.transform.k);
      });
    svg.call(zoom);

    function showTip(event, text) {
      const rect = frame.getBoundingClientRect();
      tip.textContent = text;
      tip.hidden = false;
      tip.style.left = `${event.clientX - rect.left + 12}px`;
      tip.style.top = `${event.clientY - rect.top + 12}px`;
    }
    shapes.on("mousemove", (event, f) => {
      const code = f.properties.code;
      if (!code) { tip.hidden = true; return; }
      showTip(event, I18N.t("requests.mapCountry", { country: countryName(code), count: nf(perCountry.get(code) || 0) }));
    }).on("mouseleave", () => { tip.hidden = true; })
      .on("click", (event, f) => { if (f.properties.code) focus(f); });
    dots.on("mousemove", (event, p) => {
      showTip(event, I18N.t("requests.mapPlace", { place: `${placeName(p)} (${p.country})`, count: nf(p.requests) }));
    }).on("mouseleave", () => { tip.hidden = true; });
    frame.append(tip);

    // Zoom to a country and list its regions and cities
    function focus(feature) {
      const [[x0, y0], [x1, y1]] = path.bounds(feature);
      const k = Math.min(40, 0.85 / Math.max((x1 - x0) / width, (y1 - y0) / height));
      svg.transition().duration(600).call(zoom.transform,
        d3.zoomIdentity.translate(width / 2, height / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2));
      shapes.classed("is-focus", f => f === feature);
      listCountry(feature.properties.code);
    }

    function listCountry(code) {
      side.replaceChildren();
      const total = perCountry.get(code) || 0;
      const head = document.createElement("h3");
      head.textContent = I18N.t("requests.mapCountry", { country: countryName(code), count: nf(total) });
      side.append(head);
      const mine = data.places.filter(p => p.country === code);
      const regions = d3.rollups(mine, v => d3.sum(v, p => p.requests), p => p.region || "")
        .sort((a, b) => b[1] - a[1]);
      if (!mine.length || (regions.length === 1 && !regions[0][0])) {
        const none = document.createElement("p");
        none.className = "field-msg";
        none.textContent = I18N.t("requests.mapNoPlaces");
        side.append(none);
        return;
      }
      const list = document.createElement("ul");
      list.className = "map-regions";
      for (const [region, n] of regions) {
        const item = document.createElement("li");
        const name = document.createElement("strong");
        name.textContent = `${region || I18N.t("requests.mapNoRegion")} · ${nf(n)}`;
        item.append(name);
        const cities = mine.filter(p => (p.region || "") === region && p.city);
        if (cities.length) {
          const sub = document.createElement("ul");
          cities.slice(0, 20).forEach(p => {
            const li = document.createElement("li");
            li.textContent = `${p.city} · ${nf(p.requests)}`;
            sub.append(li);
          });
          item.append(sub);
        }
        list.append(item);
      }
      side.append(list);
    }

    // Buttons: zoom in, out and back to the whole world
    const tools = document.createElement("div");
    tools.className = "map-tools";
    [["+", "requests.mapZoomIn", () => svg.transition().call(zoom.scaleBy, 2)],
     ["−", "requests.mapZoomOut", () => svg.transition().call(zoom.scaleBy, 0.5)],
     ["⟲", "requests.mapReset", () => { svg.transition().call(zoom.transform, d3.zoomIdentity); shapes.classed("is-focus", false); side.replaceChildren(intro()); }],
    ].forEach(([label, key, act]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-ghost btn-small";
      button.textContent = label;
      button.setAttribute("aria-label", I18N.t(key));
      button.title = I18N.t(key);
      button.addEventListener("click", act);
      tools.append(button);
    });
    frame.append(tools);

    // Legend: the shades from one request to the most of a country, and the circles
    const legend = document.createElement("p");
    legend.className = "map-legend";
    const ramp = document.createElement("span");
    ramp.className = "map-ramp";
    ramp.style.background = `linear-gradient(to right, ${LOW}, ${HIGH})`;
    legend.append(document.createTextNode("1 "), ramp, document.createTextNode(` ${nf(max)} · `));
    const dot = document.createElement("span");
    dot.className = "map-dot";
    legend.append(dot, document.createTextNode(" " + I18N.t("requests.mapCities")));
    box.append(legend);

    function intro() {
      const p = document.createElement("p");
      p.className = "field-msg";
      p.textContent = I18N.t("requests.mapSummary", { located: nf(data.located), total: nf(data.total),
                                                      countries: nf(perCountry.size) });
      return p;
    }
    side.append(intro());
    return { focus: code => { const f = countries.find(c => c.properties.code === code); if (f) focus(f); } };
  }

  return { render, load };
})();
