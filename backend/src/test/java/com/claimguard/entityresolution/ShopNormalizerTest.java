package com.claimguard.entityresolution;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ShopNormalizerTest {

    private final ShopNormalizer normalizer = new ShopNormalizer();

    @Test
    void legalSuffixAndCasingDoNotChangeTheCanonicalForm() {
        String a = normalizer.normalize("SpeedFix Auto Works");
        String b = normalizer.normalize("SPEEDFIX AUTO WORKS PVT LTD");

        assertThat(a).isEqualTo(b);
    }

    @Test
    void ampersandSonsAndAndSonsNormalizeTheSame() {
        String a = normalizer.normalize("Sharma & Sons Garage");
        String b = normalizer.normalize("Sharma and Sons Garage");

        assertThat(a).isEqualTo(b);
    }

    @Test
    void genuinelyDifferentShopsNormalizeDifferently() {
        String a = normalizer.normalize("SpeedFix Auto Works");
        String b = normalizer.normalize("Metro Motors");

        assertThat(a).isNotEqualTo(b);
    }
}
