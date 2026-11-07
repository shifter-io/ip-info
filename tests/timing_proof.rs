// Throwaway (#15): proves that a test over 60 s turns a pull request run red
// through the Timing step. Reverted in the same pull request.
#[test]
fn timing_proof_sleeps_61_s() {
    std::thread::sleep(std::time::Duration::from_secs(61));
}
