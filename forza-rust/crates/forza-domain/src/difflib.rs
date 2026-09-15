//! Faithful port of the subset of Python's `difflib` used by the normalizer:
//! `SequenceMatcher(None, a, b).ratio()` and `get_close_matches`.
//!
//! Autojunk is not applied because reference names are far below the length
//! threshold where it activates, so results are identical to the default
//! Python behavior for this project's inputs.

use std::collections::HashMap;

struct Blocks {
    a: Vec<char>,
    b_len: usize,
    b2j: HashMap<char, Vec<usize>>,
}

impl Blocks {
    fn new(a: &str, b: &str) -> Self {
        let mut b2j: HashMap<char, Vec<usize>> = HashMap::new();
        for (index, ch) in b.chars().enumerate() {
            b2j.entry(ch).or_default().push(index);
        }
        let b_len = b.chars().count();
        Self {
            a: a.chars().collect(),
            b_len,
            b2j,
        }
    }

    /// Recursive longest-matching-block decomposition over `[alo,ahi)x[blo,bhi)`.
    fn collect(
        &self,
        alo: usize,
        ahi: usize,
        blo: usize,
        bhi: usize,
        out: &mut Vec<(usize, usize, usize)>,
    ) {
        let mut best_i = alo;
        let mut best_j = blo;
        let mut best_size: usize = 0;
        let mut j2len: HashMap<usize, usize> = HashMap::new();

        for (offset, ch) in self.a[alo..ahi].iter().enumerate() {
            let i = alo + offset;
            let mut next_j2len: HashMap<usize, usize> = HashMap::new();
            if let Some(indices) = self.b2j.get(ch) {
                for &j in indices {
                    if j < blo {
                        continue;
                    }
                    if j >= bhi {
                        break;
                    }
                    let k = j
                        .checked_sub(1)
                        .and_then(|prev| j2len.get(&prev))
                        .copied()
                        .unwrap_or(0)
                        + 1;
                    next_j2len.insert(j, k);
                    if k > best_size {
                        best_i = i + 1 - k;
                        best_j = j + 1 - k;
                        best_size = k;
                    }
                }
            }
            j2len = next_j2len;
        }

        if best_size == 0 {
            return;
        }
        let (i, j, k) = (best_i, best_j, best_size);
        self.collect(alo, i, blo, j, out);
        out.push((i, j, k));
        self.collect(i + k, ahi, j + k, bhi, out);
    }

    fn matched_total(&self) -> usize {
        let mut blocks = Vec::new();
        self.collect(0, self.a.len(), 0, self.b_len, &mut blocks);
        blocks.iter().map(|(_, _, k)| k).sum()
    }

    fn ratio(&self) -> f64 {
        let total = self.a.len() + self.b_len;
        if total == 0 {
            return 1.0;
        }
        2.0 * self.matched_total() as f64 / total as f64
    }
}

/// Similarity between two strings in [0.0, 1.0]: `2*M / T`.
pub fn ratio(a: &str, b: &str) -> f64 {
    Blocks::new(a, b).ratio()
}

/// Return up to `n` possibilities with `ratio >= cutoff`, sorted by ratio
/// descending then lexicographically ascending — matching Python semantics.
pub fn get_close_matches(
    word: &str,
    possibilities: &[String],
    n: usize,
    cutoff: f64,
) -> Vec<String> {
    let mut scored: Vec<(f64, &String)> = Vec::new();
    for candidate in possibilities {
        let r = ratio(word, candidate);
        if r >= cutoff {
            scored.push((r, candidate));
        }
    }
    scored.sort_by(|a, b| {
        b.0.partial_cmp(&a.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.1.cmp(b.1))
    });
    scored.into_iter().take(n).map(|(_, s)| s.clone()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identical_strings_ratio_one() {
        assert!((ratio("abc", "abc") - 1.0).abs() < 1e-9);
    }

    #[test]
    fn disjoint_strings_ratio_zero() {
        assert_eq!(ratio("abc", "xyz"), 0.0);
    }

    #[test]
    fn known_ratios_match_python() {
        assert!((ratio("abcd", "abce") - 0.75).abs() < 1e-9);
        let r = ratio("abcdef", "fabced");
        assert!((r - 2.0 * 4.0 / 12.0).abs() < 1e-9);
    }

    #[test]
    fn close_matches_order_and_cutoff() {
        let pool: Vec<String> = vec![
            "Fujimi Kaidan".to_string(),
            "Fuji Speedway GT".to_string(),
            "Fuji Speedway".to_string(),
            "Circuit de Spa".to_string(),
        ];
        let matches = get_close_matches("Fuji Speeway", &pool, 1, 0.75);
        assert_eq!(matches.first().map(String::as_str), Some("Fuji Speedway"));
    }
}
