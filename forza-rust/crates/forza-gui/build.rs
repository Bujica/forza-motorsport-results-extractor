fn main() {
    // Build scripts abort the build on panic; unwrap is the conventional
    // pattern here (see slint docs).
    #[allow(clippy::unwrap_used)]
    {
        slint_build::compile("ui/main.slint").unwrap();
    }
}
