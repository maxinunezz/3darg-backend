/**
 * Convierte el <select id="id_category"> (agrupado por <optgroup>, ver
 * products/admin.py::_GroupedCategoryIterator) en dos selects encadenados:
 * "Categoría" (la raíz / el <optgroup>) y "Subcategoría" (sus hijas).
 *
 * El select original sigue siendo el único campo que Django submitea
 * (name="category") — este script solo lo oculta y lo mantiene
 * sincronizado con los dos selects nuevos, así que el guardado del form
 * no cambia en absoluto.
 */
(function () {
  "use strict";

  function init() {
    var original = document.getElementById("id_category");
    if (!original) return;

    var groups = parseGroups(original);

    var wrapper = original.closest(".related-widget-wrapper") || original;
    var container = document.createElement("div");
    container.className = "category-cascade";

    var rootSelect = document.createElement("select");
    rootSelect.id = "id_category_root";
    var subSelect = document.createElement("select");
    subSelect.id = "id_category_sub";

    var rootLabel = document.createElement("label");
    rootLabel.setAttribute("for", "id_category_root");
    rootLabel.textContent = "Categoría: ";
    rootLabel.style.marginRight = "4px";

    var subLabel = document.createElement("label");
    subLabel.setAttribute("for", "id_category_sub");
    subLabel.textContent = "Subcategoría: ";
    subLabel.style.cssText = "margin-left:12px;margin-right:4px;";

    container.appendChild(rootLabel);
    container.appendChild(rootSelect);
    container.appendChild(subLabel);
    container.appendChild(subSelect);

    wrapper.parentNode.insertBefore(container, wrapper);
    wrapper.style.display = "none";

    // El "+" nativo de Django para agregar una Category queda dentro del
    // wrapper oculto — lo reubicamos junto a "Subcategoría" para que siga
    // siendo usable.
    var addLink = wrapper.querySelector(".add-related, .related-widget-wrapper-link");
    if (addLink) {
      container.appendChild(addLink);
    }

    function fillRootSelect(selectedValue) {
      rootSelect.innerHTML = "";
      groups.forEach(function (group) {
        var opt = document.createElement("option");
        opt.value = group.key;
        opt.textContent = group.label;
        rootSelect.appendChild(opt);
      });
      var group = groupForValue(selectedValue);
      if (group) rootSelect.value = group.key;
    }

    function fillSubSelect(groupKey, selectedValue) {
      var group = findGroup(groupKey);
      subSelect.innerHTML = "";
      if (!group || group.standalone) {
        subSelect.disabled = true;
        subSelect.style.display = "none";
        subLabel.style.display = "none";
        return;
      }
      subSelect.disabled = false;
      subSelect.style.display = "";
      subLabel.style.display = "";
      group.options.forEach(function (opt) {
        var el = document.createElement("option");
        el.value = opt.value;
        el.textContent = opt.label;
        subSelect.appendChild(el);
      });
      if (selectedValue && group.options.some(function (o) { return o.value === selectedValue; })) {
        subSelect.value = selectedValue;
      }
    }

    function groupForValue(value) {
      return groups.find(function (group) {
        return group.standalone
          ? group.key === value
          : group.options.some(function (o) { return o.value === value; });
      });
    }

    function findGroup(key) {
      return groups.find(function (group) { return group.key === key; });
    }

    function syncUiFromOriginal() {
      var group = groupForValue(original.value);
      fillRootSelect(original.value);
      if (group) fillSubSelect(group.key, original.value);
    }

    function applyToOriginal() {
      var value = subSelect.disabled ? rootSelect.value : subSelect.value;
      if (value && original.value !== value) {
        original.value = value;
        original.dispatchEvent(new Event("change"));
      }
    }

    rootSelect.addEventListener("change", function () {
      fillSubSelect(rootSelect.value, null);
      applyToOriginal();
    });
    subSelect.addEventListener("change", applyToOriginal);

    // Si el "+" de Django agrega una Category nueva, dispara 'change' en
    // el select original — reconstruimos los grupos desde las <option>
    // ya actualizadas por Django y re-sincronizamos la UI.
    original.addEventListener("change", function () {
      groups = parseGroups(original);
      syncUiFromOriginal();
    });

    syncUiFromOriginal();
  }

  function parseGroups(select) {
    var groups = [];
    Array.prototype.forEach.call(select.children, function (child) {
      if (child.tagName === "OPTGROUP") {
        groups.push({
          key: "group:" + child.label,
          label: child.label,
          standalone: false,
          options: Array.prototype.map.call(child.children, function (o) {
            return { value: o.value, label: o.textContent };
          }),
        });
      } else if (child.tagName === "OPTION" && child.value) {
        groups.push({
          key: child.value,
          label: child.textContent,
          standalone: true,
        });
      }
    });
    return groups;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
