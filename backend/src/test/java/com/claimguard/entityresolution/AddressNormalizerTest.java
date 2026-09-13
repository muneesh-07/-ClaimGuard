package com.claimguard.entityresolution;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AddressNormalizerTest {

    private final AddressNormalizer normalizer = new AddressNormalizer();

    @Test
    void punctuationCasingAndAbbreviationsDoNotChangeTheCanonicalForm() {
        String a = normalizer.normalize("12 Lake View Road, Coimbatore");
        String b = normalizer.normalize("12, lake view rd. coimbatore");

        assertThat(a).isEqualTo(b);
    }

    @Test
    void wordOrderDoesNotChangeTheCanonicalForm() {
        String a = normalizer.normalize("12 Lake View Road, Coimbatore");
        String b = normalizer.normalize("Coimbatore, 12 Lake View Road");

        assertThat(a).isEqualTo(b);
    }

    @Test
    void genuinelyDifferentAddressesNormalizeDifferently() {
        String a = normalizer.normalize("12 Lake View Road, Coimbatore");
        String b = normalizer.normalize("45 Marina Street, Chennai");

        assertThat(a).isNotEqualTo(b);
    }
}
