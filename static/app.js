/* Bot Admin Panel — app.js */

(function () {
  "use strict";

  /* ── Theme system ─────────────────────────────────────── */
  var THEME_KEY = "bot_admin_theme";

  function applyTheme(theme, persist) {
    document.documentElement.setAttribute("data-theme", theme);
    if (persist) {
      try { localStorage.setItem(THEME_KEY, theme); } catch (e) {}
    }
    var toggles = document.querySelectorAll("[data-theme-toggle]");
    toggles.forEach(function (t) {
      t.textContent = theme === "dark" ? "☀️" : "🌙";
      t.setAttribute("aria-label", theme === "dark" ? "Switch to light mode" : "Switch to dark mode");
    });
  }

  var saved = null;
  try { saved = localStorage.getItem(THEME_KEY); } catch (e) {}
  var initial = saved || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(initial, false);

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-theme-toggle]");
    if (!btn) return;
    var current = document.documentElement.getAttribute("data-theme");
    applyTheme(current === "dark" ? "light" : "dark", true);
  });

  /* ── Mobile menu ───────────────────────────────────────── */
  var hamburger = document.querySelector("[data-menu-toggle]");
  var navLinks = document.querySelector("[data-nav-links]");
  if (hamburger && navLinks) {
    hamburger.addEventListener("click", function () {
      navLinks.classList.toggle("open");
    });
    navLinks.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () {
        navLinks.classList.remove("open");
      });
    });
  }

  /* ── Password eye toggle ───────────────────────────────── */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-eye-toggle]");
    if (!btn) return;
    var targetId = btn.getAttribute("data-eye-toggle");
    var input = document.getElementById(targetId);
    if (!input) return;
    var show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.textContent = show ? "🙈" : "👁️";
  });

  /* ── Copy buttons ──────────────────────────────────────── */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-copy]");
    if (!btn) return;
    var text = btn.getAttribute("data-copy");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        flashCopy(btn);
      });
    } else {
      var ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); flashCopy(btn); } catch (err) {}
      document.body.removeChild(ta);
    }
  });

  function flashCopy(btn) {
    var original = btn.textContent;
    btn.textContent = "✓ Copied";
    btn.classList.add("copied");
    setTimeout(function () {
      btn.textContent = original;
      btn.classList.remove("copied");
    }, 1500);
  }

  /* ── Client-side user search (users page) ──────────────── */
  var searchInput = document.getElementById("user-search");
  var searchRows = document.querySelectorAll("[data-search-row]");
  if (searchInput && searchRows.length) {
    searchInput.addEventListener("input", function () {
      var q = searchInput.value.trim().toLowerCase();
      searchRows.forEach(function (row) {
        var hay = (row.getAttribute("data-search-row") || "").toLowerCase();
        row.style.display = hay.indexOf(q) !== -1 ? "" : "none";
      });
    });
  }

  /* ── Auto-dismiss alerts ───────────────────────────────── */
  setTimeout(function () {
    document.querySelectorAll(".alert").forEach(function (a) {
      a.style.transition = "opacity 400ms, transform 400ms";
      a.style.opacity = "0";
      a.style.transform = "translateY(-6px)";
      setTimeout(function () { a.remove(); }, 420);
    });
  }, 5000);
})();