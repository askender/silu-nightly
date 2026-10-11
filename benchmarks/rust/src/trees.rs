// Recursive tree node counting, matches benchmarks/trees.si.

fn make_tree(depth: i64) -> i64 {
    if depth <= 0 {
        return 1;
    }
    1 + make_tree(depth - 1) + make_tree(depth - 1)
}

fn main() {
    let min_depth: i64 = 4;
    let max_depth: i64 = 14;

    let mut depth: i64 = min_depth;
    while depth <= max_depth {
        let nodes = make_tree(depth);
        println!("depth {} nodes {}", depth, nodes);
        depth += 1;
    }
}
