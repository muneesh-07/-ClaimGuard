package com.claimguard.entityresolution;

import com.google.i18n.phonenumbers.NumberParseException;
import com.google.i18n.phonenumbers.PhoneNumberUtil;
import com.google.i18n.phonenumbers.Phonenumber.PhoneNumber;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Collapses every formatting variant of the same phone number
 * (dashes, spaces, missing country code, leading trunk zero) down to
 * one canonical E.164 string, so "+91-9876500011", "9876500011" and
 * "098765 00011" all resolve to the same entity.
 */
@Component
public class PhoneNormalizer {

    private final PhoneNumberUtil phoneNumberUtil = PhoneNumberUtil.getInstance();
    private final String defaultRegion;

    public PhoneNormalizer(@Value("${claimguard.entity-resolution.default-phone-region:IN}") String defaultRegion) {
        this.defaultRegion = defaultRegion;
    }

    /** Parses a raw, however-formatted phone number and returns its canonical E.164 form (e.g. "+919876500011"). */
    public String normalize(String rawPhone) {
        try {
            PhoneNumber parsed = phoneNumberUtil.parse(rawPhone, defaultRegion);
            return phoneNumberUtil.format(parsed, PhoneNumberUtil.PhoneNumberFormat.E164);
        } catch (NumberParseException e) {
            throw new IllegalArgumentException("Could not parse phone number: " + rawPhone, e);
        }
    }
}
