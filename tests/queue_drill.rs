//! Merge-queue drill (#18): passes alone and fails once the drill's docs file
//! sits beside it. The drill's own PR removes this file.

use std::path::Path;

#[test]
fn queue_drill_docs_file_absent() {
    let b = Path::new(env!("CARGO_MANIFEST_DIR")).join("docs/queue-drill-b.txt");
    assert!(
        !b.exists(),
        "queue drill: A and B pass alone and fail together"
    );
}
