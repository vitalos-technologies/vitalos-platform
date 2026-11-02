// Vitalos Super Admin client behaviour. Loaded as an external file so the CSP needs no inline script.
(function () {
  "use strict";

  function modal() {
    return document.getElementById("modal");
  }

  function closeModal() {
    var element = modal();
    if (element) element.innerHTML = "";
    document.body.classList.remove("overflow-hidden");
  }

  function showToast(message, tone) {
    var region = document.getElementById("toasts");
    if (!region || !message) return;
    var toast = document.createElement("div");
    toast.setAttribute("role", tone === "error" ? "alert" : "status");
    toast.className =
      tone === "error"
        ? "rounded-lg bg-rose-600 px-4 py-3 text-sm font-medium text-white shadow-lg"
        : "rounded-lg bg-midnight px-4 py-3 text-sm font-medium text-white shadow-lg dark:bg-slate-700";
    toast.textContent = message;
    region.appendChild(toast);
    window.setTimeout(function () {
      toast.remove();
    }, 5000);
  }

  function clearSearch() {
    var results = document.getElementById("search-results");
    if (results) results.innerHTML = "";
  }

  // ---------------------------------------------------------------------------------------------
  // Preferences live in first-party cookies so the server renders the right state (no flash).
  var root = document.documentElement;
  var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

  function setCookie(name, value) {
    var secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = name + "=" + value + "; Path=/; Max-Age=31536000; SameSite=Lax" + secure;
  }

  function isTyping(target) {
    return (
      target &&
      (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))
    );
  }

  // Sidebar: collapse to the icon rail on desktop (Ctrl/Cmd+B); off-canvas sheet below 768px.
  function sidebar() {
    return document.getElementById("sidebar");
  }

  function toggleCollapsed() {
    var collapsed = root.getAttribute("data-sidebar") !== "collapsed";
    root.setAttribute("data-sidebar", collapsed ? "collapsed" : "expanded");
    setCookie("sidebar_state", collapsed ? "collapsed" : "expanded");
    document.querySelectorAll("[data-sidebar-toggle]").forEach(function (button) {
      button.setAttribute("aria-expanded", collapsed ? "false" : "true");
      var label = button.querySelector(".nav-label");
      if (label) label.textContent = collapsed ? "Expand sidebar" : "Collapse sidebar";
    });
  }

  var sheetOpener = null;

  function openSheet(opener) {
    var element = sidebar();
    if (!element) return;
    sheetOpener = opener || document.activeElement;
    root.setAttribute("data-sidebar-open", "");
    var backdrop = document.querySelector("[data-sidebar-backdrop]");
    if (backdrop) backdrop.classList.remove("hidden");
    document.querySelectorAll("[data-sidebar-open]").forEach(function (button) {
      if (button !== root) button.setAttribute("aria-expanded", "true");
    });
    var first = element.querySelector("a, button");
    if (first) first.focus();
  }

  function closeSheet() {
    if (!root.hasAttribute("data-sidebar-open")) return;
    root.removeAttribute("data-sidebar-open");
    var backdrop = document.querySelector("[data-sidebar-backdrop]");
    if (backdrop) backdrop.classList.add("hidden");
    document.querySelectorAll("button[data-sidebar-open]").forEach(function (button) {
      button.setAttribute("aria-expanded", "false");
    });
    if (sheetOpener && sheetOpener.focus) sheetOpener.focus();
    sheetOpener = null;
  }

  function trapSheetFocus(event) {
    if (event.key !== "Tab" || !root.hasAttribute("data-sidebar-open")) return;
    var focusable = Array.prototype.filter.call(
      sidebar().querySelectorAll("a[href], button, summary, [tabindex]:not([tabindex='-1'])"),
      function (element) {
        return element.offsetParent !== null;
      },
    );
    if (!focusable.length) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  // Theme: system → light → dark → system.
  var THEMES = ["system", "light", "dark"];

  function cycleTheme() {
    var current = root.getAttribute("data-theme") || "system";
    var next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
    root.setAttribute("data-theme", next);
    setCookie("theme", next);
    document.querySelectorAll("[data-theme-label]").forEach(function (label) {
      label.textContent = next.charAt(0).toUpperCase() + next.slice(1);
    });
  }

  // Command palette (accessible combobox in a modal <dialog>).
  function palette() {
    return document.getElementById("palette");
  }

  function paletteOptions() {
    return Array.prototype.slice.call(document.querySelectorAll("#palette-list [data-palette-option]"));
  }

  function selectOption(index) {
    var options = paletteOptions();
    var input = document.querySelector("[data-palette-input]");
    if (!options.length || !input) {
      if (input) input.removeAttribute("aria-activedescendant");
      return;
    }
    var bounded = (index + options.length) % options.length;
    options.forEach(function (option, position) {
      option.setAttribute("aria-selected", position === bounded ? "true" : "false");
    });
    input.setAttribute("aria-activedescendant", options[bounded].id);
    options[bounded].scrollIntoView({ block: "nearest" });
  }

  function selectedIndex() {
    return paletteOptions().findIndex(function (option) {
      return option.getAttribute("aria-selected") === "true";
    });
  }

  function openPalette() {
    var dialog = palette();
    if (!dialog || dialog.open) return;
    closeSheet();
    dialog.showModal();
    var input = dialog.querySelector("[data-palette-input]");
    input.value = "";
    input.focus();
    if (window.htmx) window.htmx.trigger(input, "palette-open");
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (target.closest("[data-sidebar-toggle]")) toggleCollapsed();
    if (target.closest("button[data-sidebar-open]")) openSheet(target.closest("button"));
    if (target.closest("[data-sidebar-close]") || target.matches("[data-sidebar-backdrop]")) closeSheet();
    if (target.closest("[data-theme-toggle]")) cycleTheme();
    if (target.closest("[data-palette-open]")) openPalette();
    // The top bar's Refresh link: reload the address bar's URL (HTMX may have moved it on).
    if (target.closest("a[data-refresh]") && !event.metaKey && !event.ctrlKey && !event.shiftKey) {
      event.preventDefault();
      window.location.reload();
    }
    var dialog = palette();
    if (dialog && target === dialog) dialog.close(); // Click on the backdrop.
  });

  document.addEventListener("keydown", function (event) {
    var mod = event.metaKey || event.ctrlKey;
    var key = event.key.toLowerCase();
    if (mod && key === "k") {
      event.preventDefault();
      openPalette();
      return;
    }
    if (mod && key === "b" && !isTyping(event.target) && sidebar()) {
      event.preventDefault();
      toggleCollapsed();
      return;
    }
    if (event.key === "Escape") closeSheet();
    trapSheetFocus(event);
    if (event.target.matches && event.target.matches("[data-palette-input]")) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        selectOption(selectedIndex() + (event.key === "ArrowDown" ? 1 : -1));
      } else if (event.key === "Enter") {
        var options = paletteOptions();
        var chosen = options[selectedIndex()] || options[0];
        if (chosen) {
          event.preventDefault();
          window.location.assign(chosen.getAttribute("href"));
        }
      }
    }
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target && event.detail.target.id === "palette-list") selectOption(0);
  });

  if (isMac) {
    document.querySelectorAll("[data-kbd-mod]").forEach(function (element) {
      element.textContent = "⌘K";
    });
  }


  // ---------------------------------------------------------------------------------------------
  // Enquiries inbox: keyboard shortcuts, composer tabs, canned responses, list/thread on mobile.
  function inboxRoot() {
    return document.querySelector("[data-enquiries]");
  }

  function enquiryRows() {
    return Array.prototype.slice.call(document.querySelectorAll("[data-enquiry-row]"));
  }

  function markSelectedRow() {
    enquiryRows().forEach(function (row) {
      var path = new URL(row.getAttribute("href"), window.location.href).pathname;
      if (path === window.location.pathname) row.setAttribute("aria-current", "page");
      else row.removeAttribute("aria-current");
    });
  }

  function moveSelection(step) {
    var rows = enquiryRows();
    if (!rows.length) return;
    var current = rows.indexOf(document.activeElement);
    if (current === -1) {
      current = rows.findIndex(function (row) {
        return row.getAttribute("aria-current") === "page";
      });
    }
    var next = rows[Math.min(Math.max(current + step, 0), rows.length - 1)] || rows[0];
    next.focus();
    next.scrollIntoView({ block: "nearest" });
  }

  function setComposerMode(mode, focus) {
    var composer = document.querySelector("[data-composer]");
    if (!composer) return;
    composer.setAttribute("data-mode", mode);
    composer.querySelectorAll("[data-composer-tab]").forEach(function (tab) {
      tab.setAttribute("aria-selected", tab.getAttribute("data-composer-tab") === mode ? "true" : "false");
    });
    var reply = document.getElementById("composer-reply");
    var note = document.getElementById("composer-note");
    if (reply) reply.hidden = mode !== "reply";
    if (note) note.hidden = mode !== "note";
    if (focus) {
      var panel = mode === "reply" ? reply : note;
      var field = panel && panel.querySelector("textarea");
      if (field) field.focus();
    }
  }

  // Details panel beside a thread: collapsible, remembered in a cookie the server reads (no flash).
  function toggleDetails() {
    var thread = document.querySelector("[data-thread]");
    if (!thread) return;
    var collapse = thread.getAttribute("data-details") !== "collapsed";
    thread.setAttribute("data-details", collapse ? "collapsed" : "expanded");
    setCookie("enquiry_details", collapse ? "collapsed" : "expanded");
    thread.querySelectorAll("[data-details-toggle]").forEach(function (button) {
      button.setAttribute("aria-expanded", collapse ? "false" : "true");
      var label = button.querySelector("[data-details-label]");
      if (label) label.textContent = collapse ? "Show details" : "Hide details";
    });
  }

  function clickAction(name) {
    var button = document.querySelector('[data-action="' + name + '"]');
    if (button) button.click();
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-details-toggle]")) toggleDetails();
    var tab = event.target.closest("[data-composer-tab]");
    if (tab) setComposerMode(tab.getAttribute("data-composer-tab"), true);
    var back = event.target.closest("[data-back-to-list]");
    if (back && inboxRoot()) {
      event.preventDefault();
      inboxRoot().setAttribute("data-open", "list");
      window.history.pushState({}, "", back.getAttribute("href"));
    }
  });

  document.addEventListener("change", function (event) {
    var select = event.target.closest("[data-canned-select]");
    if (!select || !select.value) return;
    var option = select.options[select.selectedIndex];
    var field = select.form && select.form.querySelector("[data-composer-body]");
    if (field) {
      field.value = (field.value ? field.value.replace(/\s*$/, "") + "\n\n" : "") + option.getAttribute("data-body");
      field.focus();
    }
    select.value = "";
  });

  document.addEventListener("keydown", function (event) {
    if (!inboxRoot() || event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return;
    if (document.querySelector("dialog[open]")) return;
    var handlers = {
      j: function () { moveSelection(1); },
      k: function () { moveSelection(-1); },
      r: function () { setComposerMode("reply", true); },
      n: function () { setComposerMode("note", true); },
      e: function () { clickAction("resolve"); },
      a: function () { clickAction("assign-me"); },
      s: function () { clickAction("spam"); },
      d: toggleDetails,
      "/": function () {
        var search = document.querySelector("[data-enquiry-search]");
        if (search) search.focus();
      },
      "?": function () {
        var help = document.getElementById("enquiry-shortcuts");
        if (help) help.showModal();
      },
    };
    var handler = handlers[event.key];
    if (handler) {
      event.preventDefault();
      handler();
    }
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    var target = event.detail.target;
    if (!target) return;
    if (target.id === "enquiry-thread") {
      if (inboxRoot()) inboxRoot().setAttribute("data-open", "thread");
      markSelectedRow();
      var composer = target.querySelector("[data-composer]");
      if (composer) setComposerMode(composer.getAttribute("data-mode") || "reply", false);
    }
    if (target.id === "enquiry-list") markSelectedRow();
  });

  window.addEventListener("popstate", function () {
    if (inboxRoot() && !/\/enquiries\/VIT-\d+\/?$/.test(window.location.pathname)) {
      inboxRoot().setAttribute("data-open", "list");
    }
  });

  // Sign-out confirmation: the menu button opens a <dialog>; without JS the form posts directly.
  var logoutReturn = null;
  function logoutDialog() {
    var dialog = document.getElementById("logout-dialog");
    return dialog && typeof dialog.showModal === "function" ? dialog : null;
  }
  document.addEventListener("click", function (event) {
    var dialog = logoutDialog();
    if (!dialog) return;
    var open = event.target.closest("[data-confirm-logout]");
    if (open) {
      event.preventDefault();
      logoutReturn = open;
      dialog.showModal();
      var cancel = dialog.querySelector("[data-close-logout]");
      if (cancel) cancel.focus();
    } else if (event.target.closest("[data-close-logout]") || event.target === dialog) {
      dialog.close();
    }
  });
  document.addEventListener(
    "close",
    function (event) {
      if (event.target.id !== "logout-dialog" || !logoutReturn) return;
      var details = logoutReturn.closest("details[data-menu]");
      if (details) details.setAttribute("open", "");
      logoutReturn.focus();
      logoutReturn = null;
    },
    true,
  );

  document.addEventListener("vsa-close-modal", closeModal);
  document.addEventListener("vsa-toast", function (event) {
    showToast(event.detail && event.detail.message, event.detail && event.detail.tone);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeModal();
      clearSearch();
      document.querySelectorAll("details[open][data-menu]").forEach(function (menu) {
        menu.removeAttribute("open");
      });
    }
  });

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (target.closest("[data-close-modal]") || target.matches("[data-modal-backdrop]")) {
      event.preventDefault();
      closeModal();
    }
    if (!target.closest("[data-search]")) clearSearch();
    document.querySelectorAll("details[open][data-menu]").forEach(function (menu) {
      if (!menu.contains(target)) menu.removeAttribute("open");
    });
    var copy = target.closest("[data-copy]");
    if (copy) {
      var source = document.getElementById(copy.getAttribute("data-copy"));
      if (source && navigator.clipboard) {
        navigator.clipboard.writeText(source.textContent.trim()).then(function () {
          copy.textContent = "Copied";
        });
      }
    }
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target && event.detail.target.id === "modal") {
      document.body.classList.add("overflow-hidden");
      var first = event.detail.target.querySelector(
        "input:not([type=hidden]):not([type=checkbox]), select, textarea",
      );
      if (first) first.focus();
    }
  });

  document.addEventListener("htmx:responseError", function (event) {
    var status = event.detail.xhr ? event.detail.xhr.status : 0;
    var message =
      status === 403
        ? "You do not have permission to do that."
        : status === 429
          ? "Too many attempts. Please wait and try again."
          : "Something went wrong. Please try again.";
    showToast(message, "error");
  });

  document.addEventListener("htmx:sendError", function () {
    showToast("Network error. Check your connection and try again.", "error");
  });

  // Section menus (Settings, Account & security): below lg the menu is a scrollable row. Bring a link fully into
  // view there without moving the page: the current section on load and after the Settings region swaps, and any
  // link that takes keyboard focus (browsers leave a partly visible one where it is, cutting off its focus ring).
  function revealInMenu(link) {
    var menu = link && link.closest(".settings-menu");
    if (!menu || menu.scrollWidth <= menu.clientWidth) return;
    var box = menu.getBoundingClientRect();
    var rect = link.getBoundingClientRect();
    if (rect.left < box.left + 8) menu.scrollLeft -= box.left + 8 - rect.left;
    else if (rect.right > box.right - 8) menu.scrollLeft += rect.right - (box.right - 8);
  }
  function revealCurrentSection() {
    revealInMenu(document.querySelector('.settings-menu a[aria-current="page"]'));
  }
  revealCurrentSection();
  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target && event.detail.target.id === "settings-region") revealCurrentSection();
  });
  document.addEventListener("focusin", function (event) {
    if (event.target.closest && event.target.closest(".settings-menu")) revealInMenu(event.target);
  });

  // Sidebar dropdowns (Mail): show or hide the child links.
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-nav-toggle]");
    if (!toggle) return;
    var list = document.getElementById(toggle.getAttribute("aria-controls"));
    var open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (list) list.hidden = !open;
  });

  // Email template editor: insert a merge variable at the caret of the last focused text field.
  var lastTemplateField = null;
  document.addEventListener("focusin", function (event) {
    var field = event.target;
    if (field.closest && field.closest("[data-template-form]") && field.matches("input[type=text], textarea")) {
      lastTemplateField = field;
    }
  });
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-insert-variable]");
    if (!button) return;
    event.preventDefault();
    var token = button.getAttribute("data-insert-variable");
    var field = lastTemplateField && document.body.contains(lastTemplateField) ? lastTemplateField : null;
    if (!field) {
      if (navigator.clipboard) navigator.clipboard.writeText(token);
      showToast("Copied " + token + ". Click into a field to insert variables.", "info");
      return;
    }
    var start = field.selectionStart == null ? field.value.length : field.selectionStart;
    var end = field.selectionEnd == null ? start : field.selectionEnd;
    field.setRangeText(token, start, end, "end");
    field.focus();
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });

  // Confirmations: one styled <dialog> (partials/confirm_dialog.html) instead of window.confirm, for
  // data-confirm forms (or their submit button), hx-confirm requests and Use template's Send. Resolves
  // true only on the confirm button; Cancel, Escape and a click outside the box all resolve false.
  var confirmState = null;

  function splitQuestion(text) {
    var at = text.indexOf("?");
    if (at === -1 || at === text.length - 1) return { title: text, body: "" };
    return { title: text.slice(0, at + 1), body: text.slice(at + 1).trim() };
  }

  function confirmDialog(options) {
    var dialog = document.getElementById("confirm-dialog");
    if (!dialog || typeof dialog.showModal !== "function") {
      return Promise.resolve(window.confirm([options.title, options.body].filter(Boolean).join("\n\n")));
    }
    if (dialog.open) return Promise.resolve(false); // one question at a time; the modal blocks the page
    dialog.querySelector("[data-confirm-title]").textContent = options.title || "Are you sure?";
    var body = dialog.querySelector("[data-confirm-body]");
    body.textContent = options.body || "";
    body.hidden = !options.body;
    var details = dialog.querySelector("[data-confirm-details]");
    details.textContent = "";
    (options.details || []).forEach(function (row) {
      if (!row[1]) return;
      var term = document.createElement("dt");
      term.className = "muted";
      term.textContent = row[0];
      var value = document.createElement("dd");
      value.className = "break-words font-medium";
      value.textContent = row[1];
      details.appendChild(term);
      details.appendChild(value);
    });
    details.hidden = details.childElementCount === 0;
    var note = dialog.querySelector("[data-confirm-note]");
    note.textContent = options.note || "";
    note.hidden = !options.note;
    var ok = dialog.querySelector("[data-confirm-ok]");
    ok.textContent = options.confirmLabel || "Confirm";
    ok.className = "btn " + (options.danger ? "btn-danger" : "btn-primary");
    return new Promise(function (resolve) {
      confirmState = { resolve: resolve, opener: document.activeElement };
      dialog.returnValue = "";
      dialog.showModal();
      dialog.querySelector("[data-confirm-cancel]").focus();
    });
  }

  document.addEventListener("click", function (event) {
    var dialog = document.getElementById("confirm-dialog");
    if (!dialog || !dialog.open) return;
    if (event.target.closest("[data-confirm-ok]")) dialog.close("ok");
    else if (event.target.closest("[data-confirm-cancel]") || event.target === dialog) dialog.close("cancel");
  });
  document.addEventListener(
    "close",
    function (event) {
      if (event.target.id !== "confirm-dialog" || !confirmState) return;
      var state = confirmState;
      confirmState = null;
      if (state.opener && state.opener.isConnected && state.opener.focus) state.opener.focus();
      state.resolve(event.target.returnValue === "ok");
    },
    true,
  );

  function confirmOptions(source, text) {
    var parts = splitQuestion(text);
    return {
      title: source.getAttribute("data-confirm-title") || parts.title,
      body: source.getAttribute("data-confirm-title") ? text : parts.body,
      confirmLabel: source.getAttribute("data-confirm-label") || "Confirm",
      danger: source.hasAttribute("data-confirm-danger"),
      note: source.getAttribute("data-confirm-note") || "",
    };
  }

  // Plain form posts that need a confirm, on the form or its submit button (no inline handlers: the
  // CSP allows only nonced scripts). After a yes, the same submit runs again, marked as confirmed.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.getAttribute) return;
    var submitter = event.submitter;
    var source = submitter && submitter.hasAttribute("data-confirm") ? submitter : form;
    var message = source.getAttribute("data-confirm");
    if (!message) return;
    if (form.hasAttribute("data-confirmed")) {
      form.removeAttribute("data-confirmed");
      return;
    }
    event.preventDefault();
    confirmDialog(confirmOptions(source, message)).then(function (yes) {
      if (!yes) return;
      form.setAttribute("data-confirmed", "");
      if (form.requestSubmit) form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
      else form.submit();
    });
  });

  // HTMX requests: Use template's Send shows who it goes to; any hx-confirm uses the same dialog.
  document.addEventListener("htmx:confirm", function (event) {
    var element = event.target;
    if (element.matches && element.matches("[data-use-send]")) {
      event.preventDefault();
      var field = document.getElementById("use-recipient");
      var recipient = field ? field.value.trim() : "";
      if (!recipient) {
        useStatus("Add the recipient's email address to send.", true);
        return;
      }
      confirmDialog({
        title: "Send this email now?",
        details: [
          ["To", recipient],
          ["From", element.getAttribute("data-use-from")],
          ["Subject", element.getAttribute("data-use-subject")],
        ],
        note: element.hasAttribute("data-use-draft") ? "This template is a draft: its wording is not yet approved." : "",
        confirmLabel: "Send email",
      }).then(function (yes) {
        if (yes) event.detail.issueRequest(true);
      });
      return;
    }
    var question = event.detail && event.detail.question;
    if (!question) return;
    event.preventDefault();
    confirmDialog(confirmOptions(element, question)).then(function (yes) {
      if (yes) event.detail.issueRequest(true);
    });
  });

  // Use template: copy buttons. The server renders the email for this recipient (and audits it);
  // the clipboard write starts inside the click so Safari and Chrome accept it, with the payload as a promise.
  function useStatus(message, failed) {
    var region = document.getElementById("use-status");
    if (!region) return;
    region.setAttribute("data-state", failed ? "error" : "ok");
    region.textContent = "";
    window.setTimeout(function () {
      region.textContent = message;
    }, 50);
  }

  function usePayload(button) {
    var form = document.getElementById("use-form");
    var data = new FormData(form);
    data.append("action", button.getAttribute("data-use-copy"));
    return fetch(button.getAttribute("data-use-url"), {
      method: "POST",
      body: data,
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    }).then(function (response) {
      return response.json().then(
        function (body) {
          if (!response.ok) throw new Error(body.error || "Could not prepare the email.");
          return body;
        },
        function () {
          throw new Error("Could not prepare the email.");
        },
      );
    });
  }

  function textBlob(value) {
    return new Blob([value], { type: "text/plain" });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-use-copy]");
    if (!button || button.disabled) return;
    event.preventDefault();
    var action = button.getAttribute("data-use-copy");
    var labels = { copy_subject: "subject", copy_email: "email", copy_text: "plain text" };
    var payload = usePayload(button);
    var rich = action === "copy_email" && window.ClipboardItem && navigator.clipboard && navigator.clipboard.write;
    var done;
    if (!navigator.clipboard) {
      payload.catch(function () {});
      useStatus("This browser cannot copy to the clipboard here. Use Download .eml instead.", true);
      return;
    }
    if (window.ClipboardItem && navigator.clipboard.write) {
      var item = {
        "text/plain": payload.then(function (body) {
          return textBlob(action === "copy_subject" ? body.subject : body.text);
        }),
      };
      if (rich) {
        item["text/html"] = payload.then(function (body) {
          return new Blob([body.html], { type: "text/html" });
        });
      }
      done = navigator.clipboard.write([new window.ClipboardItem(item)]);
    } else {
      // No ClipboardItem: plain text only.
      done = payload.then(function (body) {
        return navigator.clipboard.writeText(action === "copy_subject" ? body.subject : body.text);
      });
    }
    done.then(
      function () {
        var plainOnly = action === "copy_email" && !rich;
        useStatus(
          "Copied " + labels[action] + (plainOnly ? " as plain text (this browser cannot copy the layout)." : "."),
          false,
        );
      },
      function (error) {
        payload.catch(function () {});
        useStatus(
          error && error.message && error.name !== "NotAllowedError" ? error.message : "Could not copy. Try again.",
          true,
        );
      },
    );
  });

  // Bulk actions on list pages: row checkboxes, "select all on this page" and the action bar. Without
  // JavaScript the bar stays visible and the form still posts; the server rejects an empty selection.
  function bulkItems() {
    return Array.prototype.slice.call(document.querySelectorAll("[data-bulk-item]"));
  }

  function syncBulk() {
    var bar = document.querySelector("[data-bulk-bar]");
    if (!bar) return;
    var items = bulkItems();
    var checked = items.filter(function (item) {
      return item.checked;
    }).length;
    var all = document.querySelector("[data-bulk-all]");
    if (all) {
      all.checked = items.length > 0 && checked === items.length;
      all.indeterminate = checked > 0 && checked < items.length;
    }
    var count = bar.querySelector("[data-bulk-count]");
    if (count) count.textContent = checked ? checked + " selected" : "Select items to act on them";
    bar.classList.toggle("hidden", checked === 0);
  }

  document.addEventListener("change", function (event) {
    var target = event.target;
    if (!target.matches) return;
    if (target.matches("[data-bulk-all]")) {
      bulkItems().forEach(function (item) {
        item.checked = target.checked;
      });
      syncBulk();
    } else if (target.matches("[data-bulk-item]")) {
      syncBulk();
    }
  });

  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-bulk-clear]")) return;
    bulkItems().forEach(function (item) {
      item.checked = false;
    });
    syncBulk();
  });

  // Back/forward restores checkbox state; recount on load and on show.
  window.addEventListener("pageshow", syncBulk);
  syncBulk();

  // ---------------------------------------------------------------------------------------------
  // Busy states: button spinners (full-page and HTMX submissions), a blurred "Saving…" overlay for
  // full-page POST submissions, and a slim progress bar for HTMX navigations that swap main content.
  // Opt a form out of the overlay with data-no-submit-overlay.
  var SVG_NS = "http://www.w3.org/2000/svg";
  var busyButtons = [];
  var submitting = false;

  function spinnerNode() {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.setAttribute("class", "btn-spinner h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none");
    var track = document.createElementNS(SVG_NS, "circle");
    track.setAttribute("cx", "12");
    track.setAttribute("cy", "12");
    track.setAttribute("r", "9");
    track.setAttribute("stroke", "currentColor");
    track.setAttribute("stroke-width", "3");
    track.setAttribute("opacity", "0.25");
    var arc = document.createElementNS(SVG_NS, "path");
    arc.setAttribute("d", "M21 12a9 9 0 0 0-9-9");
    arc.setAttribute("stroke", "currentColor");
    arc.setAttribute("stroke-width", "3");
    arc.setAttribute("stroke-linecap", "round");
    svg.appendChild(track);
    svg.appendChild(arc);
    return svg;
  }

  function isButtonLike(element) {
    if (!element || element.nodeType !== 1) return false;
    if (element.tagName === "BUTTON") return element.type !== "reset";
    if (element.tagName === "INPUT") return element.type === "submit" || element.type === "button";
    return element.tagName === "A" && element.classList.contains("btn");
  }

  function setBusy(button) {
    if (!isButtonLike(button) || button.getAttribute("aria-busy") === "true") return;
    button.setAttribute("aria-busy", "true");
    if (button.tagName === "A") {
      button.setAttribute("aria-disabled", "true");
      button.classList.add("pointer-events-none");
    } else {
      button.disabled = true;
    }
    if (button.tagName !== "INPUT") {
      var icon = button.querySelector(":scope > svg");
      if (icon) {
        icon.classList.add("hidden");
        icon.setAttribute("data-spinner-hid", "");
      }
      button.insertBefore(spinnerNode(), button.firstChild);
    }
    busyButtons.push(button);
  }

  function clearBusy(button) {
    var index = busyButtons.indexOf(button);
    if (index !== -1) busyButtons.splice(index, 1);
    button.removeAttribute("aria-busy");
    if (button.tagName === "A") {
      button.removeAttribute("aria-disabled");
      button.classList.remove("pointer-events-none");
    } else {
      button.disabled = false;
    }
    button.querySelectorAll(":scope > .btn-spinner").forEach(function (node) {
      node.remove();
    });
    button.querySelectorAll(":scope > svg[data-spinner-hid]").forEach(function (node) {
      node.classList.remove("hidden");
      node.removeAttribute("data-spinner-hid");
    });
  }

  function submitOverlay() {
    return document.getElementById("submit-overlay");
  }

  function showSubmitOverlay(label) {
    var overlay = submitOverlay();
    if (!overlay) return;
    var text = overlay.querySelector("[data-submit-overlay-text]");
    if (text) text.textContent = label;
    overlay.hidden = false;
    submitting = true;
  }

  function hideSubmitOverlay() {
    var overlay = submitOverlay();
    if (overlay) overlay.hidden = true;
    submitting = false;
  }

  function overlayLabel(form, submitter) {
    var explicit = form.getAttribute("data-submit-label");
    if (explicit) return explicit;
    var text = ((submitter && (submitter.value || submitter.textContent)) || "").trim().toLowerCase();
    return /^(save|publish|create|add|update|apply|confirm|send|import)/.test(text)
      ? "Saving…"
      : "Working…";
  }

  // Full-page submissions. Deferred one tick so handlers that cancel the submit (confirm prompts,
  // validation, HTMX) have run first; the form data is read before the button is disabled.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || form.tagName !== "FORM") return;
    if (submitting) {
      event.preventDefault();
      return;
    }
    if (event.defaultPrevented) return;
    var submitter = event.submitter;
    window.setTimeout(function () {
      if (event.defaultPrevented) return;
      if (submitter) setBusy(submitter);
      var method = (form.getAttribute("method") || "get").toLowerCase();
      var target = form.getAttribute("target");
      var submitterTarget = submitter && submitter.getAttribute("formtarget");
      var skip =
        method !== "post" ||
        form.hasAttribute("data-no-submit-overlay") ||
        form.hasAttribute("hx-post") ||
        form.hasAttribute("download") ||
        (target && target !== "_self") ||
        (submitterTarget && submitterTarget !== "_self");
      if (!skip) showSubmitOverlay(overlayLabel(form, submitter));
    }, 0);
  });

  // Back/forward restore from the bfcache: never leave the page stuck in a busy state.
  window.addEventListener("pageshow", function () {
    busyButtons.slice().forEach(clearBusy);
    hideSubmitOverlay();
  });

  // HTMX requests: spinner on the triggering button; progress bar for navigations.
  function requestButton(detail) {
    var elt = detail.elt;
    if (!elt) return null;
    if (elt.tagName === "FORM") {
      var triggering = detail.requestConfig && detail.requestConfig.triggeringEvent;
      var submitter = triggering && triggering.submitter;
      if (isButtonLike(submitter)) return submitter;
      if (triggering && triggering.type && triggering.type !== "submit") return null;
      return elt.querySelector("button[type='submit'], button:not([type]), input[type='submit']");
    }
    return isButtonLike(elt) ? elt : null;
  }

  function navigationRequest(detail) {
    var main = document.getElementById("main");
    return Boolean(
      detail.elt &&
        detail.target &&
        detail.elt.hasAttribute &&
        detail.elt.hasAttribute("hx-push-url") &&
        main &&
        main.contains(detail.target),
    );
  }

  var progressCount = 0;

  function progress(on) {
    var bar = document.getElementById("nav-progress");
    progressCount = Math.max(0, progressCount + (on ? 1 : -1));
    if (bar) bar.hidden = progressCount === 0;
  }

  document.addEventListener("htmx:beforeRequest", function (event) {
    var detail = event.detail;
    var button = requestButton(detail);
    if (button) {
      if (button.getAttribute("aria-busy") === "true") {
        event.preventDefault(); // a second submit while one is in flight
        return;
      }
      setBusy(button);
    }
    if (navigationRequest(detail)) {
      detail.elt.setAttribute("data-htmx-nav", "");
      detail.target.setAttribute("aria-busy", "true");
      detail.target.classList.add("opacity-60", "animate-pulse", "motion-reduce:animate-none");
      progress(true);
    }
  });

  document.addEventListener("htmx:afterRequest", function (event) {
    var detail = event.detail;
    var button = requestButton(detail);
    if (button && button.isConnected) clearBusy(button);
    if (detail.elt && detail.elt.hasAttribute && detail.elt.hasAttribute("data-htmx-nav")) {
      detail.elt.removeAttribute("data-htmx-nav");
      progress(false);
      if (detail.target && detail.target.isConnected) {
        detail.target.removeAttribute("aria-busy");
        detail.target.classList.remove("opacity-60", "animate-pulse", "motion-reduce:animate-none");
      }
    }
  });

  // Auto-dismiss server-rendered flash messages.
  window.setTimeout(function () {
    document.querySelectorAll("[data-autodismiss]").forEach(function (element) {
      element.remove();
    });
  }, 6000);
})();
