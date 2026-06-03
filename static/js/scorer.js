(function () {
  "use strict";

  var scoreDataEl = document.getElementById("score-data");
  var defaultWeightsEl = document.getElementById("default-weights");
  if (!scoreDataEl || !defaultWeightsEl) return;

  var scoreData = JSON.parse(scoreDataEl.textContent);
  var defaultWeights = JSON.parse(defaultWeightsEl.textContent);

  var dimensions = scoreData.dimensions;
  var weights = Object.assign({}, defaultWeights);

  function computeScore(w) {
    return Math.round(dimensions.reduce(function (sum, d) {
      return sum + d.score * (w[d.id] || 0);
    }, 0));
  }

  function scoreLabel(score) {
    if (score >= 70) return "Good";
    if (score >= 40) return "Mixed";
    return "Poor";
  }

  function updateScoreDisplay() {
    var score = computeScore(weights);
    var numEl = document.getElementById("overall-score-number");
    var labelEl = document.getElementById("overall-score-label");
    if (numEl) numEl.textContent = score;
    if (labelEl) labelEl.textContent = scoreLabel(score);
    reorderCards();
  }

  function reorderCards() {
    var container = document.getElementById("dimensions");
    if (!container) return;
    var sorted = dimensions.slice().sort(function (a, b) {
      return (weights[b.id] || 0) - (weights[a.id] || 0);
    });
    sorted.forEach(function (d) {
      var card = document.getElementById("dim-card-" + d.id);
      if (card) container.appendChild(card);
    });
  }

  function redistribute(changedId, newValue) {
    var others = Object.keys(weights).filter(function (k) { return k !== changedId; });
    var remaining = 100 - newValue;
    var otherSum = others.reduce(function (s, k) { return s + weights[k] * 100; }, 0);

    weights[changedId] = newValue / 100;

    if (otherSum === 0) {
      var share = remaining / others.length / 100;
      others.forEach(function (k) { weights[k] = share; });
    } else {
      others.forEach(function (k) {
        weights[k] = (weights[k] * 100 / otherSum) * remaining / 100;
      });
    }
  }

  function syncSliders() {
    Object.keys(weights).forEach(function (id) {
      var slider = document.getElementById("weight-" + id);
      var label = document.getElementById("weight-value-" + id);
      if (slider) slider.value = Math.round(weights[id] * 100);
      if (label) label.textContent = Math.round(weights[id] * 100) + "%";
    });
  }

  document.querySelectorAll(".weight-slider").forEach(function (slider) {
    slider.addEventListener("input", function () {
      redistribute(slider.dataset.dim, parseInt(slider.value, 10));
      syncSliders();
      updateScoreDisplay();
    });
  });

  var resetBtn = document.getElementById("reset-weights");
  if (resetBtn) {
    resetBtn.addEventListener("click", function () {
      Object.keys(defaultWeights).forEach(function (k) { weights[k] = defaultWeights[k]; });
      syncSliders();
      updateScoreDisplay();
    });
  }

  updateScoreDisplay();
})();
