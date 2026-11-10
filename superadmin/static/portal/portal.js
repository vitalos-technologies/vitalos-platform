/* Vitalos client portal: small progressive enhancements. No framework, no timers that pretend work is happening. */
(function () {
  "use strict";

  // Native <dialog>: open buttons, close buttons, close on backdrop click, return focus to the opener. An opener may
  // be a link to a page that shows the dialog without JavaScript; here it opens in place instead.
  function firstField(dialog) {
    return (
      dialog.querySelector("[aria-invalid='true']") ||
      dialog.querySelector("[data-autofocus]") ||
      dialog.querySelector("textarea, input:not([type=hidden]), select, button")
    );
  }
  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-dialog-open]");
    if (opener) {
      var dialog = document.getElementById(opener.getAttribute("data-dialog-open"));
      if (dialog && typeof dialog.showModal === "function") {
        event.preventDefault();
        dialog._opener = opener;
        if (dialog.open) dialog.close();
        dialog.showModal();
        var focus = firstField(dialog);
        if (focus) focus.focus();
      }
      return;
    }
    var closer = event.target.closest("[data-dialog-close]");
    if (closer) {
      var parent = closer.closest("dialog");
      if (parent) parent.close();
      return;
    }
    if (event.target.tagName === "DIALOG" && event.target.open) {
      var rect = event.target.getBoundingClientRect();
      var inside =
        event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
      if (!inside) event.target.close();
    }
  });
  document.addEventListener(
    "close",
    function (event) {
      if (event.target.tagName === "DIALOG" && event.target._opener) event.target._opener.focus();
    },
    true
  );
  // A dialog the server rendered open (a refused upload, or ?upload=1 without JavaScript) becomes a modal here. The
  // address goes back to the page itself, so a reload neither posts again nor reopens the dialog.
  document.querySelectorAll("dialog[open][data-modal-on-load]").forEach(function (dialog) {
    if (typeof dialog.showModal !== "function") return;
    dialog.close();
    dialog.showModal();
    var focus = firstField(dialog);
    if (focus) focus.focus();
    var page = dialog.getAttribute("data-page-url");
    if (page && window.history && window.history.replaceState) window.history.replaceState(null, "", page);
  });

  // Upload dialog: the project list shows only the chosen challenge's projects. The server checks the pair anyway.
  function filterProjects(select) {
    var source = document.getElementById(select.getAttribute("data-filter-by"));
    if (!source) return;
    select.querySelectorAll("optgroup[data-challenge]").forEach(function (group) {
      var match = !source.value || group.getAttribute("data-challenge") === source.value;
      group.hidden = !match;
      group.disabled = !match;
    });
    var chosen = select.options[select.selectedIndex];
    if (chosen && chosen.parentNode.disabled) select.value = "";
  }
  function filterAllProjects() {
    document.querySelectorAll("select[data-filter-by]").forEach(filterProjects);
  }
  document.addEventListener("change", function (event) {
    if (!event.target.id) return;
    var id = window.CSS && CSS.escape ? CSS.escape(event.target.id) : event.target.id;
    document.querySelectorAll('select[data-filter-by="' + id + '"]').forEach(filterProjects);
  });
  filterAllProjects();

  // Toasts: server messages are rendered inside the aria-live region; allow dismissal, auto-hide the calm ones.
  function wireToast(toast) {
    var close = toast.querySelector("[data-toast-close]");
    if (close) close.addEventListener("click", function () { toast.remove(); });
    if (!toast.classList.contains("toast--error") && !toast.classList.contains("toast--warning")) {
      window.setTimeout(function () { toast.remove(); }, 9000);
    }
  }
  document.querySelectorAll(".toast").forEach(wireToast);

  // Busy state: stop double submissions and show that the request was sent.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || form.hasAttribute("hx-post")) return;
    var button = event.submitter || form.querySelector("button[type=submit]");
    if (button && !button.hasAttribute("data-no-busy")) {
      window.setTimeout(function () {
        button.classList.add("is-busy");
        button.setAttribute("aria-busy", "true");
      }, 0);
    }
  });
  // Back/forward cache: clear any busy state.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll(".is-busy").forEach(function (el) {
      el.classList.remove("is-busy");
      el.removeAttribute("aria-busy");
    });
  });

  // "Use this draft": copy an assistant draft into a composer. The customer edits and sends it themselves.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-fill]");
    if (!button) return;
    var target = document.querySelector(button.getAttribute("data-fill"));
    var source = document.getElementById(button.getAttribute("data-from"));
    if (target && source) {
      target.value = source.textContent.trim();
      target.focus();
      target.scrollIntoView({ block: "center" });
    }
  });

  // HTMX: mark the answer region busy while loading; announce errors in plain words.
  function htmxBusy(event, on) {
    var elt = event.detail.elt;
    if (!elt || !elt.querySelectorAll) return;
    elt.querySelectorAll("[data-htmx-busy]").forEach(function (button) {
      button.classList.toggle("is-busy", on);
      if (on) button.setAttribute("aria-busy", "true");
      else button.removeAttribute("aria-busy");
    });
  }
  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var target = event.detail.target;
    if (target) target.setAttribute("aria-busy", "true");
    htmxBusy(event, true);
  });
  document.body.addEventListener("htmx:afterRequest", function (event) {
    var target = event.detail.target;
    if (target) target.removeAttribute("aria-busy");
    htmxBusy(event, false);
  });
  // A form swapped back into an open dialog (a refused upload): keep its project filter and move focus to the
  // first field with an error, so the inline message is read out where the problem is.
  document.body.addEventListener("htmx:afterSettle", function (event) {
    filterAllProjects();
    var elt = event.detail.elt;
    var dialog = (elt && elt.isConnected && elt.closest && elt.closest("dialog[open]")) || document.querySelector("dialog[open]");
    if (!dialog) return;
    var invalid = dialog.querySelector("[aria-invalid='true']");
    if (invalid) invalid.focus();
  });
  document.body.addEventListener("htmx:responseError", function (event) {
    var target = event.detail.target;
    if (target) {
      target.innerHTML =
        '<p class="notice notice--warn" role="alert">That did not work. Nothing was changed. Please try again, or ask in the discussion.</p>';
    }
  });
  document.body.addEventListener("htmx:sendError", function (event) {
    var target = event.detail.target;
    if (target) {
      target.innerHTML =
        '<p class="notice notice--warn" role="alert">We could not reach the portal. Check your connection and try again.</p>';
    }
  });

  // Show the chosen file name next to a file input (helps on mobile where the control is terse).
  document.addEventListener("change", function (event) {
    var input = event.target;
    if (input.matches && input.matches("input[type=file][data-names]")) {
      var out = document.getElementById(input.getAttribute("data-names"));
      if (out) out.textContent = input.files.length ? input.files[0].name : "";
    }
  });

  // Account settings menu: one page per section, and the server marks the current item with aria-current. At 52rem or
  // narrower the menu is a scrollable chip row. Bring a chip fully into view there without moving the page: the
  // current one on load, and any chip that takes keyboard focus (browsers leave a partly visible one where it is,
  // cutting off its focus ring).
  function revealChip(chip) {
    var row = chip && chip.closest(".settings__menu");
    if (!row || row.scrollWidth <= row.clientWidth) return;
    var box = row.getBoundingClientRect();
    var rect = chip.getBoundingClientRect();
    if (rect.left < box.left + 8) row.scrollLeft -= box.left + 8 - rect.left;
    else if (rect.right > box.right - 8) row.scrollLeft += rect.right - (box.right - 8);
  }
  revealChip(document.querySelector('[data-settings-nav] a[aria-current="page"]'));
  document.addEventListener("focusin", function (event) {
    if (event.target.closest && event.target.closest("[data-settings-nav]")) revealChip(event.target);
  });

  // Installable app (ADR-056, Phase 1). The server sets data-sw on <html> only on the customer surface (the portal
  // host or the local /portal/ mount), never in staff preview. The worker caches public static files and the
  // offline page only; see sw.js for the privacy rule.
  var root = document.documentElement;
  var swUrl = root.getAttribute("data-sw");
  var swScope = root.getAttribute("data-sw-scope");
  if (!swUrl || !swScope) return;

  if ("serviceWorker" in navigator && window.isSecureContext) {
    var register = function () {
      navigator.serviceWorker.register(swUrl, { scope: swScope }).catch(function () {
        // The portal works without the worker; there is nothing to tell the customer.
      });
    };
    if (document.readyState === "complete") register();
    else window.addEventListener("load", register);
  }

  // Account › Install the app. The server shows the manual steps; this swaps in what fits the device.
  // No automatic banner anywhere: the browser's own install prompt is held until the customer asks for it here.
  var install = document.querySelector("[data-install]");
  var deferredPrompt = null;
  function standalone() {
    return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  }
  function showInstall(state) {
    if (!install) return;
    install.querySelectorAll("[data-install-state]").forEach(function (el) {
      el.hidden = el.getAttribute("data-install-state") !== state;
    });
  }
  var ios =
    /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (standalone()) showInstall("installed");
  else if (ios) showInstall("ios");
  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferredPrompt = event;
    if (!standalone()) showInstall("prompt");
  });
  window.addEventListener("appinstalled", function () {
    deferredPrompt = null;
    showInstall("installed");
  });
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-install-button]");
    if (!button || !deferredPrompt) return;
    var prompt = deferredPrompt;
    deferredPrompt = null;
    prompt.prompt();
    prompt.userChoice
      .then(function (choice) {
        showInstall(choice && choice.outcome === "accepted" ? "installed" : "manual");
      })
      .catch(function () {
        showInstall("manual");
      });
  });

  // Push notifications (ADR-056, Phase 2). The server renders what it knows (push off, or the member's devices);
  // this works out THIS device's state: unsupported, iOS not installed, off, on or blocked. The browser's permission
  // prompt only ever follows a click on "Turn on". A notification says only what kind of thing happened.
  var ENDPOINT_KEY = "vitalos.push.endpoint"; // this browser's endpoint once turned on here (rotation check only)
  var pushSupported =
    "serviceWorker" in navigator && "PushManager" in window && "Notification" in window && window.isSecureContext;

  function remembered() {
    try {
      return window.localStorage.getItem(ENDPOINT_KEY);
    } catch (error) {
      return null;
    }
  }
  function remember(endpoint) {
    try {
      if (endpoint) window.localStorage.setItem(ENDPOINT_KEY, endpoint);
      else window.localStorage.removeItem(ENDPOINT_KEY);
    } catch (error) {
      // Private mode or blocked storage: rotation is then picked up from Notifications on this device instead.
    }
  }
  function withTimeout(promise) {
    return new Promise(function (resolve, reject) {
      var timer = window.setTimeout(function () {
        reject(new Error("timeout"));
      }, 10000);
      promise.then(
        function (value) {
          window.clearTimeout(timer);
          resolve(value);
        },
        function (error) {
          window.clearTimeout(timer);
          reject(error);
        }
      );
    });
  }
  function currentSubscription() {
    return withTimeout(navigator.serviceWorker.ready).then(function (registration) {
      return registration.pushManager.getSubscription();
    });
  }
  function csrfToken() {
    try {
      var headers = JSON.parse(document.body.getAttribute("hx-headers") || "{}");
      if (headers["X-CSRFToken"]) return headers["X-CSRFToken"];
    } catch (error) {
      // fall back to a form token
    }
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }
  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(body),
    }).then(function (response) {
      return response
        .json()
        .catch(function () {
          return {};
        })
        .then(function (data) {
          return { ok: response.ok && data.ok !== false, status: response.status, message: data.message || "" };
        });
    });
  }
  function refusal(message) {
    var error = new Error(message);
    error.fromServer = true;
    return error;
  }
  function keyBytes(base64url) {
    var text = base64url.replace(/-/g, "+").replace(/_/g, "/");
    text += "===".slice((text.length + 3) % 4);
    var raw = window.atob(text);
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function sameKey(subscription, key) {
    var current = subscription.options && subscription.options.applicationServerKey;
    if (!current) return true; // older browsers do not expose it
    current = new Uint8Array(current);
    if (current.length !== key.length) return false;
    for (var i = 0; i < key.length; i++) if (current[i] !== key[i]) return false;
    return true;
  }
  function digest(text) {
    return window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)).then(function (buffer) {
      return Array.prototype.map
        .call(new Uint8Array(buffer), function (byte) {
          return ("0" + byte.toString(16)).slice(-2);
        })
        .join("");
    });
  }

  // On any portal page: if the browser replaced this device's subscription since it was turned on here, register
  // the new one quietly. Never enrols a browser that was not turned on here (nothing remembered, or signed out).
  var syncUrl = root.getAttribute("data-push-sync");
  if (syncUrl && pushSupported && Notification.permission === "granted") {
    currentSubscription()
      .then(function (subscription) {
        document.querySelectorAll("[data-push-endpoint]").forEach(function (input) {
          input.value = subscription ? subscription.endpoint : "";
        });
        var before = remembered();
        if (!subscription || !before || subscription.endpoint === before) return;
        return postJson(syncUrl + "?sync=1", subscription.toJSON()).then(function (result) {
          if (result.ok) remember(subscription.endpoint);
        });
      })
      .catch(function () {
        // Best effort only.
      });
  }
  // Signing out turns notifications off for this browser (the form carries its endpoint) and forgets it here.
  document.addEventListener(
    "submit",
    function (event) {
      if (event.target.matches && event.target.matches("[data-sign-out]")) remember("");
    },
    true
  );

  var card = document.querySelector("[data-push][data-push-key]");
  if (!card) return;
  var pushKey = keyBytes(card.getAttribute("data-push-key"));
  var known = (card.getAttribute("data-push-devices") || "").split(",").filter(Boolean);
  function showPush(state) {
    card.querySelectorAll("[data-push-state]").forEach(function (el) {
      el.hidden = el.getAttribute("data-push-state") !== state;
    });
    card.setAttribute("data-push-current", state);
  }
  function say(message) {
    var out = card.querySelector("[data-push-status]");
    if (out) out.textContent = message || "";
  }
  function busy(button, on) {
    button.disabled = on;
    button.classList.toggle("is-busy", on);
    if (on) button.setAttribute("aria-busy", "true");
    else button.removeAttribute("aria-busy");
  }
  function explain(error, fallback) {
    say(error && error.fromServer && error.message ? error.message : fallback);
  }
  function refreshPush() {
    if (ios && !standalone()) return showPush("ios");
    if (!pushSupported) return showPush("unsupported");
    if (Notification.permission === "denied") return showPush("blocked");
    currentSubscription()
      .then(function (subscription) {
        if (!subscription || Notification.permission !== "granted" || !sameKey(subscription, pushKey)) {
          showPush("off");
          return;
        }
        return digest(subscription.endpoint).then(function (hash) {
          card.querySelectorAll("[data-push-device]").forEach(function (item) {
            var badge = item.querySelector("[data-push-this]");
            if (badge) badge.hidden = item.getAttribute("data-push-device") !== hash;
          });
          showPush(known.indexOf(hash) >= 0 ? "on" : "off");
        });
      })
      .catch(function () {
        showPush("unsupported");
      });
  }
  function turnOn(button) {
    busy(button, true);
    say("");
    Promise.resolve(Notification.requestPermission())
      .then(function (permission) {
        if (permission !== "granted") {
          showPush(permission === "denied" ? "blocked" : "off");
          if (permission !== "denied") say("Notifications weren't allowed. You can try again.");
          return;
        }
        return withTimeout(navigator.serviceWorker.ready)
          .then(function (registration) {
            return registration.pushManager
              .getSubscription()
              .then(function (existing) {
                // A subscription made with an earlier server key cannot receive pushes: replace it.
                if (existing && !sameKey(existing, pushKey)) {
                  return existing.unsubscribe().then(function () {
                    return null;
                  });
                }
                return existing;
              })
              .then(function (existing) {
                return existing || registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: pushKey });
              });
          })
          .then(function (subscription) {
            return postJson(card.getAttribute("data-push-subscribe"), subscription.toJSON()).then(function (result) {
              if (!result.ok) throw refusal(result.message);
              remember(subscription.endpoint);
              window.location.reload(); // the device list and the confirmation come from the server
            });
          });
      })
      .catch(function (error) {
        explain(error, "Notifications couldn't be turned on in this browser. Email notifications still work.");
      })
      .then(function () {
        busy(button, false);
      });
  }
  function turnOff(button) {
    busy(button, true);
    say("");
    currentSubscription()
      .then(function (subscription) {
        if (!subscription) return showPush("off");
        return postJson(card.getAttribute("data-push-unsubscribe"), { endpoint: subscription.endpoint })
          .then(function (result) {
            // 404: the server had already forgotten this device. Either way the browser stops listening.
            if (!result.ok && result.status !== 404) throw refusal(result.message);
            return subscription.unsubscribe();
          })
          .then(function () {
            remember("");
            window.location.reload();
          });
      })
      .catch(function (error) {
        explain(error, "Notifications couldn't be turned off. Try again, or remove the device from the list.");
      })
      .then(function () {
        busy(button, false);
      });
  }
  function sendTest(button) {
    busy(button, true);
    say("");
    currentSubscription()
      .then(function (subscription) {
        if (!subscription) return showPush("off");
        return postJson(card.getAttribute("data-push-test"), { endpoint: subscription.endpoint }).then(function (result) {
          say(result.message || (result.ok ? "Sent." : "That didn't work. Try again in a few minutes."));
        });
      })
      .catch(function (error) {
        explain(error, "That didn't work. Try again in a few minutes.");
      })
      .then(function () {
        busy(button, false);
      });
  }
  card.addEventListener("click", function (event) {
    var on = event.target.closest("[data-push-on]");
    var off = event.target.closest("[data-push-off]");
    var test = event.target.closest("[data-push-test-button]");
    if (on) turnOn(on);
    else if (off) turnOff(off);
    else if (test) sendTest(test);
  });
  refreshPush();
})();
