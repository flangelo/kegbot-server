/**
 * Unit tests for fullscreen-realtime.js.
 *
 * That file is a plain (non-module) browser script that declares its state and
 * handlers as top-level globals. To exercise it in isolation we wrap the source
 * in a `new Function(...)` that returns the handlers plus references to the
 * internal state objects, giving each test a fresh, independent module instance.
 */
import { readFileSync } from "fs";
import { resolve } from "path";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

// Under the jsdom environment import.meta.url is an http:// URL, so resolve the
// source from the project root (vitest runs with cwd at the repo root) instead.
const SOURCE = readFileSync(
  resolve(process.cwd(), "pykeg/web/static/js/fullscreen-realtime.js"),
  "utf8"
);

function loadModule() {
  const factory = new Function(
    SOURCE +
      "\nreturn {" +
      "  handlePourUpdate, handlePourEnded, removePour, buildPourCard," +
      "  renderPourPanel, handleTapState," +
      "  pourOrder, currentPours, pourSettled, pourBaselines," +
      "  CONFIG: FULLSCREEN_REALTIME_CONFIG" +
      "};"
  );
  return factory();
}

function pour(overrides = {}) {
  return {
    event_type: "pour_update",
    tap: "kegboard.flow0",
    tap_name: "Main Tap",
    beer_name: "Test Lager",
    beer_image_url: null,
    volume_ml: 100,
    ticks: 272,
    user: null,
    ...overrides,
  };
}

let mod;

beforeEach(() => {
  vi.useFakeTimers();
  // The script auto-connects a WebSocket on DOMContentLoaded; stub it so loading
  // never opens a real socket.
  global.WebSocket = class {
    close() {}
  };
  document.body.innerHTML = '<div id="pour-panel"></div>';
  mod = loadModule();
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("handlePourUpdate", () => {
  it("registers a new pour and records its baseline volume", () => {
    mod.handlePourUpdate(pour({ volume_ml: 50 }));
    expect(mod.pourOrder).toContain("kegboard.flow0");
    expect(mod.pourBaselines["kegboard.flow0"]).toBe(50);
    expect(mod.pourSettled["kegboard.flow0"]).toBe(false);
  });

  it("does not duplicate a tap already pouring", () => {
    mod.handlePourUpdate(pour({ volume_ml: 50 }));
    mod.handlePourUpdate(pour({ volume_ml: 80 }));
    expect(mod.pourOrder.filter((t) => t === "kegboard.flow0")).toHaveLength(1);
    // Baseline stays anchored to the first reading.
    expect(mod.pourBaselines["kegboard.flow0"]).toBe(50);
  });

  it("switches to settled after the settle timeout", () => {
    mod.handlePourUpdate(pour());
    expect(mod.pourSettled["kegboard.flow0"]).toBe(false);
    vi.advanceTimersByTime(mod.CONFIG.settleTimeout);
    expect(mod.pourSettled["kegboard.flow0"]).toBe(true);
  });

  it("drops the pour card after the update timeout", () => {
    mod.handlePourUpdate(pour());
    expect(mod.pourOrder).toHaveLength(1);
    vi.advanceTimersByTime(mod.CONFIG.updateTimeout);
    expect(mod.pourOrder).toHaveLength(0);
    expect(mod.currentPours["kegboard.flow0"]).toBeUndefined();
  });
});

describe("handlePourEnded", () => {
  it("settles the pour immediately without dropping it", () => {
    mod.handlePourUpdate(pour());
    mod.handlePourEnded({ tap: "kegboard.flow0" });
    expect(mod.pourSettled["kegboard.flow0"]).toBe(true);
    expect(mod.pourOrder).toContain("kegboard.flow0");
  });
});

describe("buildPourCard", () => {
  it("shows poured ounces relative to the baseline", () => {
    mod.handlePourUpdate(pour({ volume_ml: 100 }));
    // 100 ml baseline + 100 ml poured = 200 ml; (200-100)/29.5735 ≈ 3.4 oz.
    const data = { ...pour({ volume_ml: 200 }) };
    const card = mod.buildPourCard(data);
    expect(card.querySelector(".pour-amount").textContent).toBe("3.4 oz");
    expect(card.querySelector(".pour-title").textContent).toBe("Pouring…");
    expect(card.querySelector(".pour-tap-name").textContent).toBe("Main Tap");
  });

  it("labels the card 'Poured' once settled", () => {
    mod.handlePourUpdate(pour());
    mod.handlePourEnded({ tap: "kegboard.flow0" });
    const card = mod.buildPourCard(pour({ volume_ml: 200 }));
    expect(card.querySelector(".pour-title").textContent).toBe("Poured");
  });
});

describe("renderPourPanel", () => {
  it("hides the panel when there are no pours", () => {
    mod.renderPourPanel();
    expect(document.getElementById("pour-panel").style.display).toBe("none");
  });

  it("shows one card per active pour", () => {
    mod.handlePourUpdate(pour({ tap: "kegboard.flow0", tap_name: "Tap A" }));
    mod.handlePourUpdate(pour({ tap: "kegboard.flow1", tap_name: "Tap B" }));
    const panel = document.getElementById("pour-panel");
    expect(panel.style.display).toBe("flex");
    expect(panel.querySelectorAll(".pour-card")).toHaveLength(2);
  });
});

describe("handleTapState", () => {
  it("updates volume, temperature and illustration DOM nodes", () => {
    document.body.innerHTML =
      '<span data-tap-volume="1"></span>' +
      '<span data-tap-temp="1"></span>' +
      '<img data-tap-illustration="1" />';

    // Minimal jQuery shim backed by the real DOM.
    global.$ = (selector) => {
      const els = [...document.querySelectorAll(selector)];
      return {
        length: els.length,
        text: (t) => els.forEach((e) => (e.textContent = t)),
        attr: (a, v) => els.forEach((e) => e.setAttribute(a, v)),
      };
    };

    mod.handleTapState({
      taps: [
        {
          tap_id: 1,
          volume_label: "120.0 oz",
          temp_str: "39.2° F",
          illustration_url: "/static/images/keg/full/keg-srm14-5.png",
        },
      ],
    });

    expect(document.querySelector('[data-tap-volume="1"]').textContent).toBe(
      "120.0 oz remaining"
    );
    expect(document.querySelector('[data-tap-temp="1"]').textContent).toBe(
      "Keg temperature: 39.2° F"
    );
    expect(
      document.querySelector('[data-tap-illustration="1"]').getAttribute("src")
    ).toBe("/static/images/keg/full/keg-srm14-5.png");
  });
});
