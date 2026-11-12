// Dependency-free DOM contract test for the optional adaptive panel.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

class Element {
  constructor() { this.children = []; this.style = {}; this.textContent = ""; this.hidden = false; }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.children.push(item); }
  replaceChildren() { this.children = []; }
}
const elements = { adaptivePanel: new Element(), adaptiveCards: new Element() };
const source = fs.readFileSync(path.join(__dirname, "../dashboard/app.js"), "utf8");
const start = source.indexOf("function renderAdaptive(");
const end = source.indexOf("\n}", start) + 2;
const context = { document: { getElementById: id => elements[id], createElement: () => new Element() }, Date, JSON };
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
context.renderAdaptive(undefined);
assert.equal(elements.adaptivePanel.hidden, true);
context.renderAdaptive({ status: "observation_only_no_live_route", decision_time: 0, evaluation: {
  regime: { regime: "UNCERTAIN" }, reasons: ["<script>bad()</script>"], score: { score: 0.3 },
} });
assert.equal(elements.adaptivePanel.hidden, false);
assert.equal(elements.adaptiveCards.children.length, 15);
const reasons = elements.adaptiveCards.children.find(card => card.children[0].textContent === "Rejection reasons");
assert.ok(reasons.children[1].textContent.includes("<script>bad()</script>"));
assert.equal(reasons.children[1].children.length, 0); // Text, never interpreted markup.
context.renderAdaptive(undefined);
assert.equal(elements.adaptiveCards.children.length, 0);
console.log("Adaptive dashboard DOM contract passed: hidden defaults, observation fields, safe text, legacy reset");
