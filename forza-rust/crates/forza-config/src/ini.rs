//! Minimal ordered INI document used by the settings writer.
//!
//! Mirrors the observable behavior of Python's `configparser` for this
//! application: section/key insertion order is preserved, unknown keys and
//! sections survive a read/write round trip, comments are dropped, values are
//! written as `key = value`, and every section block is followed by one blank
//! line.

/// One INI section with its keys in file order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IniSection {
    pub name: String,
    pub keys: Vec<(String, String)>,
}

/// An ordered INI document.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct IniDocument {
    pub sections: Vec<IniSection>,
}

impl IniDocument {
    /// Parse INI text. Missing or malformed input yields an empty document;
    /// the settings writer only round-trips files the loader already accepts.
    pub fn parse(text: &str) -> Self {
        let mut doc = Self::default();
        let mut current: Option<usize> = None;
        for line in text.lines() {
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with(';') {
                continue;
            }
            if let Some(name) = trimmed.strip_prefix('[').and_then(|r| r.strip_suffix(']')) {
                let name = name.trim().to_string();
                if doc.section_index(&name).is_none() {
                    doc.sections.push(IniSection {
                        name: name.clone(),
                        keys: Vec::new(),
                    });
                }
                current = doc.section_index(&name);
                continue;
            }
            if let Some((key, value)) = split_pair(line)
                && let Some(index) = current
            {
                let section = &mut doc.sections[index];
                match section.keys.iter_mut().find(|(k, _)| *k == key) {
                    Some(slot) => slot.1 = value,
                    None => section.keys.push((key, value)),
                }
            }
        }
        doc
    }

    fn section_index(&self, name: &str) -> Option<usize> {
        self.sections.iter().position(|s| s.name == name)
    }

    /// Read a key inside a section.
    pub fn get(&self, section: &str, key: &str) -> Option<&str> {
        self.sections
            .iter()
            .find(|s| s.name == section)
            .and_then(|s| s.keys.iter().find(|(k, _)| k == key))
            .map(|(_, v)| v.as_str())
    }

    /// Create the section when absent (at the end, like `add_section`).
    pub fn ensure_section(&mut self, name: &str) {
        if self.section_index(name).is_none() {
            self.sections.push(IniSection {
                name: name.to_string(),
                keys: Vec::new(),
            });
        }
    }

    /// Set a key preserving its position; append when new.
    pub fn set(&mut self, section: &str, key: &str, value: &str) {
        self.ensure_section(section);
        let index = self.section_index(section).unwrap_or_default();
        let keys = &mut self.sections[index].keys;
        match keys.iter_mut().find(|(k, _)| k == key) {
            Some(slot) => slot.1 = value.to_string(),
            None => keys.push((key.to_string(), value.to_string())),
        }
    }

    /// Remove a key when present.
    pub fn remove_key(&mut self, section: &str, key: &str) {
        if let Some(index) = self.section_index(section) {
            self.sections[index].keys.retain(|(k, _)| k != key);
        }
    }

    /// Remove an entire section when present.
    pub fn remove_section(&mut self, name: &str) {
        self.sections.retain(|s| s.name != name);
    }

    /// Serialize with configparser-compatible layout.
    pub fn render(&self) -> String {
        let mut out = String::new();
        for section in &self.sections {
            out.push('[');
            out.push_str(&section.name);
            out.push_str("]\n");
            for (key, value) in &section.keys {
                out.push_str(key);
                out.push_str(" = ");
                out.push_str(value);
                out.push('\n');
            }
            out.push('\n');
        }
        out
    }
}

fn split_pair(line: &str) -> Option<(String, String)> {
    let position = line.find(['=', ':'])?;
    let key = line[..position].trim();
    if key.is_empty() {
        return None;
    }
    let value = line[position + 1..].trim().to_string();
    Some((key.to_string(), value))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_preserves_order_and_unknown_keys() {
        let doc = IniDocument::parse("[b]\nx = 1\n\n[a]\nkeep_me = yes\nx = 2\nextra = 3\n");
        assert_eq!(doc.sections[0].name, "b");
        assert_eq!(doc.get("a", "keep_me"), Some("yes"));
        assert_eq!(doc.get("a", "x"), Some("2"));
    }

    #[test]
    fn set_keeps_position_and_appends_new_keys() {
        let mut doc = IniDocument::parse("[s]\nfirst = 1\nsecond = 2\n");
        doc.set("s", "second", "9");
        doc.set("s", "third", "3");
        doc.set("t", "other", "4");
        assert_eq!(
            doc.render(),
            "[s]\nfirst = 1\nsecond = 9\nthird = 3\n\n[t]\nother = 4\n\n"
        );
    }

    #[test]
    fn remove_key_and_section() {
        let mut doc = IniDocument::parse("[s]\na = 1\nb = 2\n\n[z]\nc = 3\n");
        doc.remove_key("s", "a");
        doc.remove_section("z");
        assert_eq!(doc.render(), "[s]\nb = 2\n\n");
    }

    #[test]
    fn comments_are_dropped_like_configparser() {
        let doc = IniDocument::parse("; note\n[s]\n# another\na = 1\n");
        assert_eq!(doc.render(), "[s]\na = 1\n\n");
    }
}
