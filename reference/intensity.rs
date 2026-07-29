//! 基于震级和距离估算烈度
//!
//! 使用 EarthQuakeWarning 项目的衰减模型：
//! `I = 1.363 * M + 2.941 - 1.494 * ln(D + 7.0)`

/// 估算烈度值（不设上限，低于 0 归 0）
pub(crate) fn estimate_intensity(magnitude: f64, distance_km: f64) -> f64 {
    if !magnitude.is_finite() || !distance_km.is_finite() || magnitude <= 0.0 || distance_km < 0.0 {
        return 0.0;
    }

    let intensity = 1.363 * magnitude + 2.941 - 1.494 * (distance_km + 7.0).ln();

    if intensity < 0.0 { 0.0 } else { intensity }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_estimate_intensity() {
        let i1 = estimate_intensity(7.0, 10.0);
        assert!(i1 >= 5.0);

        let i2 = estimate_intensity(7.0, 100.0);
        assert!(i2 < i1);

        let i3 = estimate_intensity(5.0, 50.0);
        assert!((1.0..=6.0).contains(&i3));

        let i4 = estimate_intensity(4.0, 10.0);
        let i4_far = estimate_intensity(4.0, 100.0);
        assert!(i4_far < i4);
    }

    #[test]
    fn test_known_values() {
        let v1 = estimate_intensity(5.1, 280.0);
        assert!((v1 - 1.4370).abs() < 0.01);

        let v2 = estimate_intensity(4.8, 280.0);
        assert!((v2 - 1.0281).abs() < 0.01);

        let v3 = estimate_intensity(7.0, 10.0);
        assert!((v3 - 8.249).abs() < 0.01);
    }

    #[test]
    fn rejects_non_finite_inputs() {
        assert_eq!(estimate_intensity(f64::NAN, 10.0), 0.0);
        assert_eq!(estimate_intensity(5.0, f64::INFINITY), 0.0);
        assert_eq!(estimate_intensity(f64::INFINITY, 10.0), 0.0);
    }

    #[test]
    fn intensity_decreases_with_distance() {
        let near = estimate_intensity(6.0, 10.0);
        let far = estimate_intensity(6.0, 500.0);
        assert!(far < near);
    }
}
