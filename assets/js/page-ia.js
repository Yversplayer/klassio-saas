// KLASSIO — Assistant IA conversationnel (lecture seule).
// L'IA ne modifie jamais rien depuis ce fichier : chaque envoi passe par
// POST /api/ai/ask, dont le backend n'expose que des outils de lecture
// (backend/ai_assistant.py). Les boutons d'action ici ne font QUE naviguer.
(function () {
  "use strict";
  var api = window.KlassioApi, ui = window.KlassioAdmin;

  var SUGGESTIONS = {
    directeur: [
      "Analyse ma situation financière", "Quels sont les plus gros impayés ?",
      "Quels élèves ont plusieurs absences ?", "Montre-moi les incidents récents",
    ],
    discipline: [
      "Montre-moi les incidents récents", "Quels élèves ont plusieurs retards ?",
      "Combien d'élèves de la 7e sont absents aujourd'hui ?", "Combien avons-nous de classes ?",
    ],
    professeur: [
      "Quels élèves de ma classe ont plusieurs retards ?", "Combien d'élèves sont inscrits ?",
      "Montre-moi les incidents récents", "Quelle est la situation financière de ma classe ?",
    ],
    parent: [
      "Quelle est la situation de mes enfants ?", "Que reste-t-il à payer ?",
      "Montre-moi le reçu de mon enfant", "Quelle est la différence entre Finance et Paiements ?",
    ],
  };

  var conversationId = null;
  var lastIntent = null;

  function mdToHtml(text) {
    var escaped = ui.escapeHtml(text);
    escaped = escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    return escaped.replace(/\n/g, "<br>");
  }

  function renderRich(rich) {
    if (!rich) return "";
    if (rich.type === "stats") {
      return '<div class="ia-rich ia-rich-stats">' + rich.items.map(function (it) {
        return '<div class="ia-rich-stat"><div class="k">' + ui.escapeHtml(it.label) + '</div><div class="v">' + ui.escapeHtml(it.value) + "</div></div>";
      }).join("") + "</div>";
    }
    if (rich.type === "table") {
      var head = "<tr>" + rich.columns.map(function (c) { return "<th>" + ui.escapeHtml(c) + "</th>"; }).join("") + "</tr>";
      var body = rich.rows.map(function (row) {
        return "<tr>" + row.map(function (cell) { return "<td>" + ui.escapeHtml(String(cell)) + "</td>"; }).join("") + "</tr>";
      }).join("");
      return '<div class="ia-rich"><table class="ia-rich-table"><thead>' + head + "</thead><tbody>" + body + "</tbody></table></div>";
    }
    return "";
  }

  function appendMessage(role, text, rich, actions) {
    document.getElementById("iaEmptyState").style.display = "none";
    var thread = document.getElementById("iaThread");
    var wrap = document.createElement("div");
    wrap.className = "ia-msg " + role;
    var actionsHtml = (actions && actions.length)
      ? '<div class="ia-msg-actions">' + actions.map(function (a) {
          return '<a class="ia-action-btn" href="' + ui.escapeHtml(a.target) + '">' + ui.escapeHtml(a.label) + "</a>";
        }).join("") + "</div>"
      : "";
    wrap.innerHTML = '<div class="ia-msg-bubble">' + mdToHtml(text) + renderRich(rich) + actionsHtml + "</div>";
    thread.appendChild(wrap);
    thread.scrollTop = thread.scrollHeight;
    return wrap;
  }

  function appendTyping() {
    document.getElementById("iaEmptyState").style.display = "none";
    var thread = document.getElementById("iaThread");
    var wrap = document.createElement("div");
    wrap.className = "ia-msg assistant";
    wrap.id = "iaTypingBubble";
    wrap.innerHTML = '<div class="ia-msg-bubble"><div class="ia-typing"><span></span><span></span><span></span></div></div>';
    thread.appendChild(wrap);
    thread.scrollTop = thread.scrollHeight;
  }

  function removeTyping() {
    var el = document.getElementById("iaTypingBubble");
    if (el) el.remove();
  }

  function sendMessage(text) {
    if (!text.trim()) return;
    appendMessage("user", text);
    document.getElementById("iaInput").value = "";
    var sendBtn = document.getElementById("iaSendBtn");
    sendBtn.disabled = true;
    appendTyping();

    api.fetch("/ai/ask", {
      method: "POST",
      body: JSON.stringify({ message: text, conversation_id: conversationId, previous_intent: lastIntent }),
    }).then(function (res) {
      removeTyping();
      sendBtn.disabled = false;
      if (!res.ok) {
        appendMessage("assistant", res.body.error || "Impossible de récupérer les informations. Réessayez.");
        return;
      }
      conversationId = res.body.conversation_id;
      lastIntent = res.body.intent;
      appendMessage("assistant", res.body.text, res.body.rich, res.body.actions);
      loadConversations();
    }).catch(function () {
      removeTyping();
      sendBtn.disabled = false;
      appendMessage("assistant", "Klassio est momentanément injoignable — le reste de l'application continue de fonctionner normalement.");
    });
  }

  document.getElementById("iaComposer").addEventListener("submit", function (e) {
    e.preventDefault();
    sendMessage(document.getElementById("iaInput").value);
  });

  function startNewConversation() {
    conversationId = null;
    lastIntent = null;
    document.getElementById("iaThread").innerHTML = "";
    var empty = document.createElement("div");
    empty.className = "ia-empty-state";
    empty.id = "iaEmptyState";
    empty.innerHTML = '<p class="ia-empty-title">Comment puis-je vous aider ?</p><div class="ia-suggestions" id="iaSuggestions"></div>';
    document.getElementById("iaThread").appendChild(empty);
    renderSuggestions();
    document.querySelectorAll(".ia-history-item").forEach(function (el) { el.classList.remove("active"); });
  }
  document.getElementById("newConvBtn").addEventListener("click", startNewConversation);

  function renderSuggestions(role) {
    var list = SUGGESTIONS[role] || SUGGESTIONS.parent;
    var el = document.getElementById("iaSuggestions");
    if (!el) return;
    if (role) renderSuggestions.role = role; else list = SUGGESTIONS[renderSuggestions.role] || list;
    el.innerHTML = list.map(function (s) {
      return '<button type="button" class="ia-suggestion-chip">' + ui.escapeHtml(s) + "</button>";
    }).join("");
    el.querySelectorAll(".ia-suggestion-chip").forEach(function (btn) {
      btn.addEventListener("click", function () { sendMessage(btn.textContent); });
    });
  }

  function loadConversations() {
    return api.fetch("/ai/conversations").then(function (res) {
      var list = document.getElementById("convList");
      if (!res.body.length) {
        list.innerHTML = '<div class="ia-history-empty">Aucune conversation pour le moment.</div>';
        return;
      }
      list.innerHTML = res.body.map(function (c) {
        return '<div class="ia-history-item' + (c.id === conversationId ? " active" : "") + '" data-conv="' + c.id + '">' +
               ui.escapeHtml(c.title) + "</div>";
      }).join("");
      list.querySelectorAll("[data-conv]").forEach(function (el) {
        el.addEventListener("click", function () { openConversation(el.dataset.conv); });
      });
    });
  }

  function openConversation(id) {
    api.fetch("/ai/conversations/" + id + "/messages").then(function (res) {
      if (!res.ok) return;
      conversationId = id;
      lastIntent = null;
      var thread = document.getElementById("iaThread");
      thread.innerHTML = "";
      res.body.forEach(function (m) {
        lastIntent = m.intent || lastIntent;
        appendMessage(m.role, m.content, m.rich, null);
      });
      document.querySelectorAll(".ia-history-item").forEach(function (el) {
        el.classList.toggle("active", el.dataset.conv === id);
      });
    });
  }

  window.KlassioAdmin.initShell("ia").then(function (ctx) {
    renderSuggestions(ctx.role);
    return loadConversations();
  });
})();
